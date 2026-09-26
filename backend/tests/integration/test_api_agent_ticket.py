# backend/tests/integration/test_api_agent_ticket.py
"""阶段 5：Agent 自动创建工单草稿（chat.py 胶水 → 现有 TicketService）。

覆盖：G2/G0 触发建草稿（actor_type=agent 审计）、幂等、高风险首轮不自动建单、
开关关闭不建单、建单失败不阻断聊天流。
"""
import json

import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

from app.config import settings
from app.main import app

from tests.integration.conftest import login_admin
from tests.integration.test_api_chat import _make_mock_graph, _collect_sse_events


@pytest.fixture
async def client():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await login_admin(c)
            yield c


def _final_state(**overrides) -> dict:
    state = {
        "final_answer": "建议送修检测",
        "route_path": "local",
        "judge_log": [],
        "intent": "troubleshooting",
        "recommended_action": "create_ticket",
        "auto_create_ticket": True,
    }
    state.update(overrides)
    return state


def _langgraph_end(output: dict) -> list[dict]:
    return [{"event": "on_chain_end", "name": "LangGraph", "data": {"output": output}}]


@pytest.mark.asyncio
async def test_agent_auto_creates_ticket_draft(client, monkeypatch):
    """auto_create_ticket=True + 开关开启 → 创建草稿，meta 带引用，审计 actor=agent。"""
    monkeypatch.setattr(settings, "AGENT_AUTO_TICKET_ENABLED", True)
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph(_langgraph_end(_final_state()))
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    meta = next(e["data"] for e in events if e["type"] == "meta")
    assert meta["recommended_action"] == "create_ticket"
    assert meta["agent_ticket"] is not None
    assert meta["agent_ticket"]["status"] == "draft"

    tickets = (await client.get("/api/tickets")).json()
    assert len(tickets) == 1
    assert tickets[0]["status"] == "draft"
    assert tickets[0]["conversation_id"] == conv_id

    # 审计事件：created，actor_type=agent
    detail = (await client.get(f"/api/tickets/{tickets[0]['id']}")).json()
    created_event = next(e for e in detail["events"] if e["event_type"] == "created")
    assert created_event["actor_type"] == "agent"


@pytest.mark.asyncio
async def test_agent_ticket_creation_is_idempotent(client, monkeypatch):
    """同一会话重复触发 → 仍是同一张草稿（服务层幂等）。"""
    monkeypatch.setattr(settings, "AGENT_AUTO_TICKET_ENABLED", True)
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    graph = _make_mock_graph(_langgraph_end(_final_state()))

    first = next(e["data"] for e in await _collect_sse_events(client, conv_id, graph, monkeypatch) if e["type"] == "meta")
    second = next(e["data"] for e in await _collect_sse_events(client, conv_id, graph, monkeypatch) if e["type"] == "meta")

    assert first["agent_ticket"]["id"] == second["agent_ticket"]["id"]
    tickets = (await client.get("/api/tickets")).json()
    assert len(tickets) == 1


@pytest.mark.asyncio
async def test_high_risk_first_occurrence_does_not_auto_create(client, monkeypatch):
    """高风险首轮：升级但不自动建单（auto_create_ticket 由规则层置 False）。"""
    monkeypatch.setattr(settings, "AGENT_AUTO_TICKET_ENABLED", True)
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    graph = _make_mock_graph(_langgraph_end(_final_state(
        recommended_action="escalate",
        auto_create_ticket=False,
        safety_level="high",
    )))
    meta = next(e["data"] for e in await _collect_sse_events(client, conv_id, graph, monkeypatch) if e["type"] == "meta")

    assert meta["recommended_action"] == "escalate"
    assert meta["agent_ticket"] is None
    assert (await client.get("/api/tickets")).json() == []


@pytest.mark.asyncio
async def test_user_requests_human_auto_creates_ticket(client, monkeypatch):
    """用户明确要人工 → escalate + 自动建草稿。"""
    monkeypatch.setattr(settings, "AGENT_AUTO_TICKET_ENABLED", True)
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    graph = _make_mock_graph(_langgraph_end(_final_state(
        recommended_action="escalate",
        auto_create_ticket=True,
        judge_log=[{"judge_type": "decide_action", "passed": True,
                    "raw_output": {"action": "escalate", "triggered_rules": ["user_requests_human"]}}],
    )))
    meta = next(e["data"] for e in await _collect_sse_events(client, conv_id, graph, monkeypatch) if e["type"] == "meta")

    assert meta["recommended_action"] == "escalate"
    assert meta["agent_ticket"] is not None
    assert meta["agent_ticket"]["status"] == "draft"


@pytest.mark.asyncio
async def test_auto_ticket_disabled_by_default(client, monkeypatch):
    """开关关闭（默认 False）→ 决策信号保留但不建单，旧行为不变。"""
    monkeypatch.setattr(settings, "AGENT_AUTO_TICKET_ENABLED", False)
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    graph = _make_mock_graph(_langgraph_end(_final_state()))
    meta = next(e["data"] for e in await _collect_sse_events(client, conv_id, graph, monkeypatch) if e["type"] == "meta")

    assert meta["recommended_action"] == "create_ticket"  # 决策信号照常透传
    assert meta["agent_ticket"] is None
    assert (await client.get("/api/tickets")).json() == []


@pytest.mark.asyncio
async def test_ticket_service_failure_does_not_break_chat(client, monkeypatch):
    """建单失败 → 只记 warning，SSE 正常完成，回答不受影响。"""
    monkeypatch.setattr(settings, "AGENT_AUTO_TICKET_ENABLED", True)
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    from app.api import tickets as tickets_module

    async def _boom(*args, **kwargs):
        raise RuntimeError("ticket store down")

    monkeypatch.setattr(tickets_module.get_service(), "create_draft_from_conversation", _boom)

    graph = _make_mock_graph(_langgraph_end(_final_state()))
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    meta = next(e["data"] for e in events if e["type"] == "meta")
    assert meta["agent_ticket"] is None
    assert events[-1]["type"] == "done"           # 流正常收尾
    assert any(e["type"] == "final" for e in events)  # 回答不受影响
