from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.query_log import QueryLogCreate
from app.services.attachment_store import AttachmentStore, LocalAttachmentStorage
from app.services.attachment_security import AttachmentValidationError
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


async def _make_attachment_service(tmp_path):
    db_path = str(tmp_path / "tickets.db")
    ticket_store = TicketStore(db_path)
    conversation_store = ConversationStore(db_path)
    query_log_store = QueryLogStore(db_path)
    storage = LocalAttachmentStorage(tmp_path / "attachments")
    attachment_store = AttachmentStore(db_path, storage=storage)
    for store in (ticket_store, conversation_store, query_log_store, attachment_store):
        await store.init()
    service = TicketService(
        ticket_store=ticket_store,
        conversation_store=conversation_store,
        query_log_store=query_log_store,
        attachment_store=attachment_store,
    )
    return service, ticket_store, conversation_store, attachment_store


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


@pytest.mark.asyncio
async def test_create_draft_promotes_ready_attachments_as_evidence(tmp_path):
    service, ticket_store, conversation_store, attachment_store = (
        await _make_attachment_service(tmp_path)
    )
    conv_id = await _seed_conversation(conversation_store)
    created = await attachment_store.create_attachment(
        conv_id, "flight.log", b"LOG DATA\n", "text/plain"
    )

    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    evidence = await ticket_store.list_evidence(ticket["id"])
    assert [(item["evidence_type"], item["evidence_id"]) for item in evidence] == [
        ("attachment", created.id)
    ]
    promoted = await attachment_store.get_attachment(conv_id, created.id)
    assert promoted.expires_at > datetime.now(timezone.utc) + timedelta(days=29)


@pytest.mark.asyncio
async def test_create_draft_compensates_when_promotion_fails(tmp_path):
    service, ticket_store, conversation_store, attachment_store = (
        await _make_attachment_service(tmp_path)
    )
    conv_id = await _seed_conversation(conversation_store)
    other_conv = await conversation_store.create_conversation(user_id="user-1")
    foreign = await attachment_store.create_attachment(
        other_conv, "other.log", b"OTHER\n", "text/plain"
    )

    with pytest.raises(AttachmentValidationError):
        await service.create_draft_from_conversation(
            "user-1", conv_id, attachment_ids=[foreign.id]
        )

    assert await ticket_store.get_by_user_conversation("user-1", conv_id) is None


@pytest.mark.asyncio
async def test_draft_summary_strips_markdown_and_leads_with_question(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await conversation_store.create_conversation(user_id="user-1")
    await conversation_store.add_message(
        conv_id, "user", "无人机机翼被砸断了可以换新吗？"
    )
    await conversation_store.add_message(
        conv_id,
        "assistant",
        "## 1. 立即安全处置\n\n- 请先确保设备**完全断电**，并`取出电池`\n"
        "- 相关风险包括[微小裂纹](https://example.com)逐渐扩展\n\n"
        "### 2. 维修建议\n\n请联系官方售后检测机臂结构。",
    )

    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    summary = ticket["problem_summary"]
    assert summary.startswith("用户问题：无人机机翼被砸断了可以换新吗？")
    assert summary.startswith("用户问题：") and "初步建议：" in summary
    for raw_markdown in ("##", "**", "`", "- 请先", "](", "https://"):
        assert raw_markdown not in summary
    assert "完全断电" in summary
    assert "取出电池" in summary


@pytest.mark.asyncio
async def test_update_draft_edits_title_and_summary(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store)
    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    updated = await service.update_draft(
        ticket["id"],
        user_id="user-1",
        title="机翼断裂更换咨询",
        summary="仓库中被砸断机翼，想了解更换流程与费用。",
    )

    assert updated["title"] == "机翼断裂更换咨询"
    assert updated["problem_summary"] == "仓库中被砸断机翼，想了解更换流程与费用。"


@pytest.mark.asyncio
async def test_update_draft_locked_after_submit_and_rejects_foreign_user(tmp_path):
    service, _, conversation_store, _ = await _make_service(tmp_path)
    conv_id = await _seed_conversation(conversation_store)
    ticket = await service.create_draft_from_conversation("user-1", conv_id)

    with pytest.raises(LookupError):
        await service.update_draft(
            ticket["id"], user_id="user-2", title="冒充者编辑"
        )
    await service.transition(
        ticket["id"], actor_type="user", actor_id="user-1", target_status="submitted"
    )
    with pytest.raises(ValueError, match="ticket_not_editable"):
        await service.update_draft(
            ticket["id"], user_id="user-1", title="迟到的编辑"
        )
