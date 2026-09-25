from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.query_log import QueryLogCreate
from app.services.conversation_store import ConversationStore
from app.services.query_log_service import QueryLogStore
from app.services.ticket_service import TicketService
from app.services.ticket_store import TicketStore


async def _make_service(tmp_path):
    db_path = str(tmp_path / "tickets.db")
    ticket_store = TicketStore(db_path)
    conversation_store = ConversationStore(db_path)
    query_log_store = QueryLogStore(db_path)
    for store in (ticket_store, conversation_store, query_log_store):
        await store.init()
    service = TicketService(
        ticket_store=ticket_store,
        conversation_store=conversation_store,
        query_log_store=query_log_store,
    )
    return service, ticket_store, conversation_store, query_log_store


async def _seed_conversation(
    conversation_store: ConversationStore,
    *,
    user_id: str = "user-1",
    high_risk: bool = False,
) -> str:
    conv_id = await conversation_store.create_conversation(
        title="无人机售后咨询", user_id=user_id
    )
    await conversation_store.add_message(
        conv_id, "user", "Mini 4 Pro 罗盘异常无法校准，应该怎么处理？"
    )
    await conversation_store.add_message(
        conv_id,
        "assistant",
        "请先远离金属干扰源，重新校准罗盘；若仍异常请立即降落并联系官方售后。"
        if high_risk
        else "请按以下步骤重新校准罗盘：进入 DJ Fly App 选择安全校准。",
        safety_flag=True if high_risk else None,
        safety_level="high" if high_risk else "none",
        safety_situation="flying" if high_risk else None,
        escalation_required=True if high_risk else None,
        intent="fault_troubleshooting",
        metadata_constraints={
            "product_model": "mini_4_pro",
            "component": "compass",
            "fault_type": "compass_abnormal",
        },
    )
    return conv_id


@pytest.mark.asyncio
async def test_create_draft_is_idempotent_and_keeps_server_safety_data(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store, high_risk=True)

    first = await service.create_draft_from_conversation("user-1", conv_id)
    second = await service.create_draft_from_conversation(
        "user-1", conv_id, actor_type="user"
    )

    assert first["id"] == second["id"]
    assert first["status"] == "draft"
    assert first["safety_level"] == "high"
    assert first["escalation_reason"]
    assert first["priority"] == "high"
    assert first["device_model"] == "mini_4_pro"
    assert first["fault_category"] == "compass_abnormal"
    assert "罗盘" in first["title"]
    assert first["problem_summary"].startswith("用户问题：")
    created_events = [
        event
        for event in await service._ticket_store.list_events(first["id"])
        if event["event_type"] == "created"
    ]
    assert len(created_events) == 1


@pytest.mark.asyncio
async def test_create_draft_requires_owned_conversation(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store, user_id="user-1")

    with pytest.raises(LookupError):
        await service.create_draft_from_conversation("user-2", conv_id)
    with pytest.raises(LookupError):
        await service.create_draft_from_conversation("user-1", "missing-conv")


@pytest.mark.asyncio
async def test_create_draft_defaults_without_safety_fields(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store, high_risk=False)

    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    assert ticket["safety_level"] == "none"
    assert ticket["escalation_reason"] is None
    assert ticket["priority"] == "normal"


@pytest.mark.asyncio
async def test_snapshot_falls_back_to_query_log(tmp_path):
    service, ticket_store, conversation_store, query_log_store = await _make_service(
        tmp_path
    )
    conv_id = await conversation_store.create_conversation(user_id="user-1")
    await conversation_store.add_message(
        conv_id, "user", "飞机在飞行中突然失控，怎么办？"
    )
    await conversation_store.add_message(conv_id, "assistant", "请立即切换姿态模式并降落。")
    await query_log_store.insert(
        QueryLogCreate(
            id=str(uuid4()),
            conversation_id=conv_id,
            user_id="user-1",
            raw_query="飞机在飞行中突然失控，怎么办？",
            safety_flag=True,
            safety_level="high",
            safety_situation="flying",
            escalation_required=True,
            intent="safety_consult",
            metadata_constraints={"product_model": "air_3", "fault_type": "flyaway"},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )

    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    assert ticket["safety_level"] == "high"
    assert ticket["device_model"] == "air_3"
    assert ticket["fault_category"] == "flyaway"
    assert ticket["escalation_reason"]


@pytest.mark.asyncio
async def test_transition_whitelist_records_events(tmp_path):
    service, ticket_store, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store)
    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    submitted = await service.transition(
        ticket["id"], actor_type="user", actor_id="user-1", target_status="submitted"
    )
    assert submitted["status"] == "submitted"

    with pytest.raises(ValueError, match="ticket_transition_not_allowed"):
        await service.transition(
            ticket["id"],
            actor_type="admin",
            target_status="resolved_pending_confirm",
        )

    await service.transition(
        ticket["id"], actor_type="admin", target_status="assigned"
    )
    in_progress = await service.transition(
        ticket["id"], actor_type="admin", target_status="in_progress"
    )
    assert in_progress["status"] == "in_progress"

    with pytest.raises(ValueError, match="ticket_transition_not_allowed"):
        await service.transition(
            ticket["id"], actor_type="user", target_status="resolved_pending_confirm"
        )

    events = await ticket_store.list_events(ticket["id"])
    transitions = [
        (event["from_status"], event["to_status"])
        for event in events
        if event["event_type"] != "created"
    ]
    assert transitions == [
        ("draft", "submitted"),
        ("submitted", "assigned"),
        ("assigned", "in_progress"),
    ]


@pytest.mark.asyncio
async def test_user_confirmation_closes_ticket_and_sets_timestamp(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store)
    ticket = await service.create_draft_from_conversation("user-1", conv_id)
    for actor, target in (
        ("user", "submitted"),
        ("admin", "assigned"),
        ("admin", "in_progress"),
        ("admin", "resolved_pending_confirm"),
    ):
        ticket = await service.transition(
            ticket["id"], actor_type=actor, target_status=target
        )

    closed = await service.transition(
        ticket["id"], actor_type="user", actor_id="user-1", target_status="closed"
    )

    assert closed["status"] == "closed"
    assert closed["user_confirmed_at"] is not None
    assert closed["closed_at"] is not None
    with pytest.raises(ValueError, match="ticket_transition_not_allowed"):
        await service.transition(
            ticket["id"], actor_type="admin", target_status="reopened"
        )


@pytest.mark.asyncio
async def test_high_risk_ticket_cannot_be_closed_by_system(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store, high_risk=True)
    ticket = await service.create_draft_from_conversation("user-1", conv_id)
    for actor, target in (
        ("user", "submitted"),
        ("admin", "assigned"),
        ("admin", "in_progress"),
        ("admin", "resolved_pending_confirm"),
    ):
        ticket = await service.transition(
            ticket["id"], actor_type=actor, target_status=target
        )

    with pytest.raises(ValueError, match="ticket_high_risk_close_forbidden"):
        await service.transition(
            ticket["id"], actor_type="system", target_status="closed"
        )
    with pytest.raises(ValueError, match="ticket_high_risk_close_forbidden"):
        await service.transition(
            ticket["id"], actor_type="agent", target_status="closed"
        )


@pytest.mark.asyncio
async def test_reopen_clears_resolution_timestamps(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store)
    ticket = await service.create_draft_from_conversation("user-1", conv_id)
    for actor, target in (
        ("user", "submitted"),
        ("admin", "assigned"),
        ("admin", "in_progress"),
        ("admin", "resolved_pending_confirm"),
    ):
        ticket = await service.transition(
            ticket["id"], actor_type=actor, target_status=target
        )

    reopened = await service.transition(
        ticket["id"], actor_type="user", actor_id="user-1", target_status="reopened"
    )

    assert reopened["status"] == "reopened"
    assert reopened["closed_at"] is None
    assert reopened["user_confirmed_at"] is None
    assert reopened["resolved_at"] is None


@pytest.mark.asyncio
async def test_agent_and_system_cannot_change_status(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store)
    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    with pytest.raises(ValueError, match="ticket_transition_actor_forbidden"):
        await service.transition(
            ticket["id"], actor_type="agent", target_status="submitted"
        )
    with pytest.raises(ValueError, match="ticket_transition_actor_forbidden"):
        await service.transition(
            ticket["id"], actor_type="system", target_status="submitted"
        )


@pytest.mark.asyncio
async def test_stale_status_transition_conflicts(tmp_path):
    service, ticket_store, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store)
    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    with pytest.raises(ValueError, match="ticket_status_conflict"):
        await ticket_store.apply_transition(
            ticket["id"],
            from_status="submitted",
            to_status="assigned",
            event={"actor_type": "admin", "event_type": "assigned"},
        )
