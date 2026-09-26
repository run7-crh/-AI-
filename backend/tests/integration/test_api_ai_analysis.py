# backend/tests/integration/test_api_ai_analysis.py
"""阶段 6：管理端 AI 分析端点（POST /api/admin/tickets/{id}/ai-analysis）。

覆盖：开关关闭 503、分析成功持久化 agent_suggestion、用户侧详情不可见、
404 / 504 错误映射。
"""
import pytest
from httpx import ASGITransport, AsyncClient
from asgi_lifespan import LifespanManager

from app.config import settings
from app.main import app

from tests.integration.conftest import login_admin


@pytest.fixture
async def client():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await login_admin(c)
            yield c


async def _create_ticket(client) -> str:
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    ticket = (await client.post(
        "/api/tickets/from-conversation", json={"conversation_id": conv_id}
    )).json()
    return ticket["id"]


class _StubAnalysisService:
    """用真实 TicketStore 持久化事件的桩服务（不触 LLM/检索器）。"""

    def __init__(self, behavior="ok"):
        self.behavior = behavior

    async def analyze(self, ticket_id: str) -> dict:
        if self.behavior == "missing":
            raise LookupError("ticket_not_found")
        if self.behavior == "boom":
            raise RuntimeError("LLM exploded")
        from app.api import admin_tickets as admin_module

        await admin_module.get_store().append_event(
            ticket_id=ticket_id,
            actor_type="agent",
            actor_id=None,
            event_type="agent_suggestion",
            from_status=None,
            to_status=None,
            body="分析摘要：疑似固件问题",
            metadata={
                "summary": "疑似固件问题",
                "product_model": "mini_4_pro",
                "handling_advice": ["先远程指导检查固件"],
                "suggested_reply": "您好，建议先重启并检查固件版本。",
                "confidence": 0.7,
                "high_risk": False,
            },
        )
        return {
            "ticket_id": ticket_id,
            "summary": "疑似固件问题",
            "suggested_reply": "您好，建议先重启并检查固件版本。",
            "handling_advice": ["先远程指导检查固件"],
            "high_risk": False,
        }


@pytest.mark.asyncio
async def test_analysis_disabled_by_default_returns_503(client, monkeypatch):
    ticket_id = await _create_ticket(client)
    monkeypatch.setattr(settings, "ADMIN_AI_ANALYSIS_ENABLED", False)
    resp = await client.post(f"/api/admin/tickets/{ticket_id}/ai-analysis")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_analysis_success_persists_and_user_cannot_see(client, monkeypatch):
    from app.api import admin_tickets as admin_module

    monkeypatch.setattr(settings, "ADMIN_AI_ANALYSIS_ENABLED", True)
    monkeypatch.setattr(admin_module, "_analysis_service", _StubAnalysisService())

    ticket_id = await _create_ticket(client)
    resp = await client.post(f"/api/admin/tickets/{ticket_id}/ai-analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == "疑似固件问题"
    assert body["suggested_reply"].startswith("您好")

    # 管理端详情：agent_suggestion 事件可见（metadata 即分析）
    admin_detail = (await client.get(f"/api/admin/tickets/{ticket_id}")).json()
    suggestion_events = [e for e in admin_detail["events"] if e["event_type"] == "agent_suggestion"]
    assert len(suggestion_events) == 1
    assert suggestion_events[0]["actor_type"] == "agent"
    assert suggestion_events[0]["metadata"]["product_model"] == "mini_4_pro"

    # 用户侧同一条工单（属主本人）：内部 AI 分析不可见
    user_detail = (await client.get(f"/api/tickets/{ticket_id}")).json()
    assert all(e["event_type"] != "agent_suggestion" for e in user_detail["events"])


@pytest.mark.asyncio
async def test_analysis_missing_ticket_returns_404(client, monkeypatch):
    from app.api import admin_tickets as admin_module

    monkeypatch.setattr(settings, "ADMIN_AI_ANALYSIS_ENABLED", True)
    monkeypatch.setattr(admin_module, "_analysis_service", _StubAnalysisService("missing"))
    resp = await client.post("/api/admin/tickets/nonexistent/ai-analysis")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_analysis_failure_returns_504(client, monkeypatch):
    from app.api import admin_tickets as admin_module

    monkeypatch.setattr(settings, "ADMIN_AI_ANALYSIS_ENABLED", True)
    monkeypatch.setattr(admin_module, "_analysis_service", _StubAnalysisService("boom"))
    resp = await client.post(await _ticket_url(client))
    assert resp.status_code == 504


async def _ticket_url(client) -> str:
    return f"/api/admin/tickets/{await _create_ticket(client)}/ai-analysis"
