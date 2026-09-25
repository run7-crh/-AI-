"""Ticket API integration coverage.

Covers the user workflow (draft → submit → confirm/reopen) and the admin
queue (filters, assignment, public replies, internal notes, closure) over
HTTP.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from asgi_lifespan import LifespanManager

from app.api import conversations as conversations_api
from app.main import app, get_ticket_store
from app.services.ticket_service import TicketService
from tests.integration.conftest import login_admin, register_and_login


async def _client():
    manager = LifespanManager(app)
    await manager.__aenter__()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return manager, client


async def _seed_conversation(user_id: str, *, high_risk: bool = False) -> str:
    store = conversations_api.get_store()
    conv_id = await store.create_conversation(user_id=user_id)
    await store.add_message(conv_id, "user", "Mini 4 Pro 罗盘异常无法校准，怎么处理？")
    await store.add_message(
        conv_id,
        "assistant",
        "请远离干扰源后重新校准罗盘；若仍异常请立即降落并联系官方售后。",
        safety_level="high" if high_risk else "none",
        safety_situation="flying" if high_risk else None,
        escalation_required=True if high_risk else None,
        metadata_constraints={
            "product_model": "mini_4_pro",
            "component": "compass",
            "fault_type": "compass_abnormal",
        },
    )
    return conv_id


async def _advance_admin_flow(ticket_id: str, targets) -> None:
    """Drive the admin side of the state machine (Task 5 will expose HTTP)."""
    service = TicketService(
        ticket_store=get_ticket_store(),
        conversation_store=conversations_api.get_store(),
    )
    for target in targets:
        await service.transition(ticket_id, actor_type="admin", target_status=target)


@pytest.mark.asyncio
async def test_user_ticket_flow_from_draft_to_confirm_and_reopen():
    manager, client = await _client()
    try:
        user = await register_and_login(client, username="ticket-owner", password="Owner-pass-1")
        conv_id = await _seed_conversation(user["id"], high_risk=True)

        anonymous_client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        try:
            anonymous = await anonymous_client.post(
                "/api/tickets/from-conversation", json={"conversation_id": conv_id}
            )
        finally:
            await anonymous_client.aclose()
        assert anonymous.status_code == 401

        created = await client.post(
            "/api/tickets/from-conversation", json={"conversation_id": conv_id}
        )
        assert created.status_code == 201, created.text
        ticket = created.json()
        assert ticket["status"] == "draft"
        assert ticket["safety_level"] == "high"
        assert ticket["escalation_reason"]
        assert ticket["device_model"] == "mini_4_pro"
        assert ticket["fault_category"] == "compass_abnormal"

        again = await client.post(
            "/api/tickets/from-conversation", json={"conversation_id": conv_id}
        )
        assert again.status_code == 201
        assert again.json()["id"] == ticket["id"]

        listed = await client.get("/api/tickets")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [ticket["id"]]

        detail = await client.get(f"/api/tickets/{ticket['id']}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["ticket"]["id"] == ticket["id"]
        assert any(event["event_type"] == "created" for event in body["events"])

        submitted = await client.post(f"/api/tickets/{ticket['id']}/submit")
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"

        message = await client.post(
            f"/api/tickets/{ticket['id']}/messages",
            json={"body": "补充：已按步骤重新校准，问题依旧。"},
        )
        assert message.status_code == 200

        await _advance_admin_flow(
            ticket["id"], ["assigned", "in_progress", "resolved_pending_confirm"]
        )
        resolved = await client.get(f"/api/tickets/{ticket['id']}")
        assert resolved.json()["ticket"]["status"] == "resolved_pending_confirm"

        reopened = await client.post(f"/api/tickets/{ticket['id']}/reopen")
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "reopened"
        assert reopened.json()["closed_at"] is None

        await _advance_admin_flow(ticket["id"], ["assigned", "in_progress", "resolved_pending_confirm"])
        closed = await client.post(f"/api/tickets/{ticket['id']}/confirm-resolution")
        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        assert closed.json()["user_confirmed_at"] is not None
    finally:
        await client.aclose()
        await manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_ticket_boundaries_and_internal_note_visibility():
    manager, client = await _client()
    try:
        user = await register_and_login(client, username="ticket-owner2", password="Owner-pass-1")
        conv_id = await _seed_conversation(user["id"])
        created = await client.post(
            "/api/tickets/from-conversation", json={"conversation_id": conv_id}
        )
        ticket_id = created.json()["id"]

        stranger_manager, stranger_client = await _client()
        try:
            await register_and_login(
                stranger_client, username="ticket-stranger2", password="Stranger-pass-1"
            )
            cross_created = await stranger_client.post(
                "/api/tickets/from-conversation", json={"conversation_id": conv_id}
            )
            assert cross_created.status_code == 404
            cross_detail = await stranger_client.get(f"/api/tickets/{ticket_id}")
            assert cross_detail.status_code == 404
            assert (
                await stranger_client.post(f"/api/tickets/{ticket_id}/submit")
            ).status_code == 404
        finally:
            await stranger_client.aclose()
            await stranger_manager.__aexit__(None, None, None)

        missing = await client.get("/api/tickets/missing-ticket")
        assert missing.status_code == 404

        invalid = await client.post(f"/api/tickets/{ticket_id}/confirm-resolution")
        assert invalid.status_code == 422

        await get_ticket_store().append_event(
            ticket_id=ticket_id,
            actor_type="admin",
            actor_id="test-admin",
            event_type="internal_note",
            from_status=None,
            to_status=None,
            body="内部判断：疑似硬件故障，需返厂检测。",
            metadata={},
        )
        detail = await client.get(f"/api/tickets/{ticket_id}")
        event_types = [event["event_type"] for event in detail.json()["events"]]
        assert "internal_note" not in event_types
        assert all("硬件故障" not in (event.get("body") or "") for event in detail.json()["events"])
    finally:
        await client.aclose()
        await manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_admin_ticket_api_requires_admin_and_supports_filters():
    manager, client = await _client()
    try:
        user = await register_and_login(client, username="ticket-owner3", password="Owner-pass-1")
        conv_id = await _seed_conversation(user["id"], high_risk=True)
        created = await client.post(
            "/api/tickets/from-conversation", json={"conversation_id": conv_id}
        )
        ticket_id = created.json()["id"]
        await client.post(f"/api/tickets/{ticket_id}/submit")

        admin_manager, admin_client = await _client()
        try:
            await login_admin(admin_client)
            forbidden = await client.get("/api/admin/tickets")
            assert forbidden.status_code == 403

            patch = await admin_client.patch(
                f"/api/admin/tickets/{ticket_id}",
                json={"status": "assigned", "assignee_user_id": "test-admin"},
            )
            assert patch.status_code == 200, patch.text
            assert patch.json()["status"] == "assigned"
            assert patch.json()["assignee_user_id"] == "test-admin"

            by_status = await admin_client.get("/api/admin/tickets", params={"status": "assigned"})
            assert [item["id"] for item in by_status.json()] == [ticket_id]
            by_assignee = await admin_client.get(
                "/api/admin/tickets", params={"assignee_user_id": "test-admin"}
            )
            assert [item["id"] for item in by_assignee.json()] == [ticket_id]
            by_safety = await admin_client.get(
                "/api/admin/tickets", params={"safety_level": "high"}
            )
            assert [item["id"] for item in by_safety.json()] == [ticket_id]
            by_priority = await admin_client.get(
                "/api/admin/tickets", params={"priority": "urgent"}
            )
            assert by_priority.json() == []
        finally:
            await admin_client.aclose()
            await admin_manager.__aexit__(None, None, None)
    finally:
        await client.aclose()
        await manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_admin_ticket_operations_produce_events():
    manager, client = await _client()
    try:
        user = await register_and_login(client, username="ticket-owner4", password="Owner-pass-1")
        conv_id = await _seed_conversation(user["id"])
        created = await client.post(
            "/api/tickets/from-conversation", json={"conversation_id": conv_id}
        )
        ticket_id = created.json()["id"]
        await client.post(f"/api/tickets/{ticket_id}/submit")

        admin_manager, admin_client = await _client()
        try:
            await login_admin(admin_client)

            patched = await admin_client.patch(
                f"/api/admin/tickets/{ticket_id}",
                json={"status": "assigned", "assignee_user_id": "test-admin"},
            )
            assert patched.status_code == 200
            assert (
                await admin_client.patch(
                    f"/api/admin/tickets/{ticket_id}", json={"status": "in_progress"}
                )
            ).status_code == 200

            note = await admin_client.post(
                f"/api/admin/tickets/{ticket_id}/events",
                json={"event_type": "internal_note", "body": "内部判断：疑似固件问题。"},
            )
            assert note.status_code == 200
            reply = await admin_client.post(
                f"/api/admin/tickets/{ticket_id}/events",
                json={"event_type": "public_reply", "body": "请先升级固件到最新版本。"},
            )
            assert reply.status_code == 200

            for status in ("waiting_user", "in_progress"):
                step = await admin_client.patch(
                    f"/api/admin/tickets/{ticket_id}", json={"status": status}
                )
                assert step.status_code == 200

            resolved = await admin_client.patch(
                f"/api/admin/tickets/{ticket_id}",
                json={
                    "status": "resolved_pending_confirm",
                    "resolution_summary": "已升级固件并重新校准指南针。",
                },
            )
            assert resolved.status_code == 200
            assert resolved.json()["resolution_summary"] == "已升级固件并重新校准指南针。"

            reopened = await admin_client.patch(
                f"/api/admin/tickets/{ticket_id}", json={"status": "reopened"}
            )
            assert reopened.status_code == 200
            assert reopened.json()["closed_at"] is None

            for status in ("assigned", "in_progress", "resolved_pending_confirm"):
                step = await admin_client.patch(
                    f"/api/admin/tickets/{ticket_id}", json={"status": status}
                )
                assert step.status_code == 200

            closed = await admin_client.patch(
                f"/api/admin/tickets/{ticket_id}", json={"status": "closed"}
            )
            assert closed.status_code == 200, closed.text
            assert closed.json()["status"] == "closed"

            admin_detail = await admin_client.get(f"/api/admin/tickets/{ticket_id}")
            admin_events = admin_detail.json()["events"]
            event_types = [event["event_type"] for event in admin_events]
            assert "internal_note" in event_types
            assert event_types.count("assigned") == 2
            assert event_types.count("reopened") == 1
            assert event_types.count("admin_closed") == 1
            assert any(
                event["event_type"] == "updated" and "assignee_user_id" in (event.get("metadata") or {}).get("changed", [])
                for event in admin_events
            )
        finally:
            await admin_client.aclose()
            await admin_manager.__aexit__(None, None, None)

        user_detail = await client.get(f"/api/tickets/{ticket_id}")
        user_event_types = [event["event_type"] for event in user_detail.json()["events"]]
        assert "internal_note" not in user_event_types
        assert "public_reply" in user_event_types
    finally:
        await client.aclose()
        await manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_draft_editing_via_patch_endpoint():
    manager, client = await _client()
    try:
        user = await register_and_login(client, username="ticket-owner5", password="Owner-pass-1")
        conv_id = await _seed_conversation(user["id"])
        created = await client.post(
            "/api/tickets/from-conversation", json={"conversation_id": conv_id}
        )
        ticket_id = created.json()["id"]

        edited = await client.patch(
            f"/api/tickets/{ticket_id}/draft",
            json={"title": "机翼断裂更换咨询", "problem_summary": "仓库中被砸断机翼，咨询更换流程。"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["title"] == "机翼断裂更换咨询"
        assert edited.json()["problem_summary"] == "仓库中被砸断机翼，咨询更换流程。"

        empty = await client.patch(
            f"/api/tickets/{ticket_id}/draft", json={}
        )
        assert empty.status_code == 422

        stranger_manager, stranger_client = await _client()
        try:
            await register_and_login(
                stranger_client, username="ticket-stranger5", password="Stranger-pass-1"
            )
            cross = await stranger_client.patch(
                f"/api/tickets/{ticket_id}/draft", json={"title": "越权编辑"}
            )
            assert cross.status_code == 404
        finally:
            await stranger_client.aclose()
            await stranger_manager.__aexit__(None, None, None)

        await client.post(f"/api/tickets/{ticket_id}/submit")
        locked = await client.patch(
            f"/api/tickets/{ticket_id}/draft", json={"title": "提交后编辑"}
        )
        assert locked.status_code == 422
    finally:
        await client.aclose()
        await manager.__aexit__(None, None, None)
