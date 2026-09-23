from datetime import datetime, timezone

import pytest

from app.services.ticket_store import TicketStore


def _ticket_payload(*, user_id: str = "user-1", conversation_id: str = "conv-1") -> dict:
    return {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "title": "遥控器无法连接",
        "problem_summary": "用户反馈遥控器无法连接飞机。",
        "priority": "normal",
        "safety_level": "none",
        "status": "draft",
    }


@pytest.mark.asyncio
async def test_init_is_idempotent_and_create_scopes_by_user(tmp_path):
    store = TicketStore(str(tmp_path / "tickets.db"))

    await store.init()
    await store.init()
    ticket = await store.create_ticket(_ticket_payload())

    assert ticket["ticket_number"].startswith("T-")
    assert await store.get_ticket(ticket["id"], user_id="user-1") is not None
    assert await store.get_ticket(ticket["id"], user_id="user-2") is None


@pytest.mark.asyncio
async def test_ticket_number_and_conversation_pair_are_unique(tmp_path):
    store = TicketStore(str(tmp_path / "tickets.db"))
    await store.init()

    first = await store.create_ticket(_ticket_payload())
    same_pair = await store.get_by_user_conversation("user-1", "conv-1")
    second = await store.create_ticket(_ticket_payload(conversation_id="conv-2"))

    assert same_pair["id"] == first["id"]
    assert first["ticket_number"] != second["ticket_number"]
    with pytest.raises(ValueError, match="ticket_conversation_exists"):
        await store.create_ticket(_ticket_payload())


@pytest.mark.asyncio
async def test_events_are_append_only_and_evidence_is_unique(tmp_path):
    store = TicketStore(str(tmp_path / "tickets.db"))
    await store.init()
    ticket = await store.create_ticket(_ticket_payload())
    timestamp = datetime.now(timezone.utc).isoformat()

    event_id = await store.append_event(
        ticket_id=ticket["id"],
        actor_type="user",
        actor_id="user-1",
        event_type="created",
        from_status=None,
        to_status="draft",
        body="创建工单草稿",
        metadata={"source": "conversation"},
        created_at=timestamp,
    )
    duplicate_event_id = await store.append_event(
        ticket_id=ticket["id"],
        actor_type="user",
        actor_id="user-1",
        event_type="created",
        from_status=None,
        to_status="draft",
        body="创建工单草稿",
        metadata={"source": "conversation"},
        created_at=timestamp,
    )
    evidence_id = await store.add_evidence(ticket["id"], "attachment", "attachment-1")
    duplicate_evidence_id = await store.add_evidence(ticket["id"], "attachment", "attachment-1")

    events = await store.list_events(ticket["id"])
    evidence = await store.list_evidence(ticket["id"])
    assert event_id
    assert duplicate_event_id != event_id
    assert len(events) == 2
    assert evidence_id
    assert duplicate_evidence_id == evidence_id
    assert len(evidence) == 1
    assert evidence[0]["evidence_id"] == "attachment-1"


@pytest.mark.asyncio
async def test_list_for_user_and_admin(tmp_path):
    store = TicketStore(str(tmp_path / "tickets.db"))
    await store.init()
    await store.create_ticket(_ticket_payload(user_id="user-1", conversation_id="conv-1"))
    await store.create_ticket(_ticket_payload(user_id="user-2", conversation_id="conv-2"))

    user_tickets = await store.list_tickets(user_id="user-1")
    all_tickets = await store.list_tickets()

    assert [item["user_id"] for item in user_tickets] == ["user-1"]
    assert {item["user_id"] for item in all_tickets} == {"user-1", "user-2"}
