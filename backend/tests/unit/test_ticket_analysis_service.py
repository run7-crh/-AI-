# backend/tests/unit/test_ticket_analysis_service.py
"""阶段 6：管理端 AI Copilot 服务（TicketAnalysisService）单元测试。

覆盖：上下文聚合与画像来源优先级、复用检索器、结构化诊断与引用校验、
高风险保守降级、agent_suggestion 事件持久化、ticket 不存在。
"""
import pytest

from app.services.ticket_analysis_service import (
    CONSERVATIVE_HANDLING_ADVICE,
    CONSERVATIVE_REPLY_TEMPLATE,
    TicketAnalysisService,
)


class FakeTicketStore:
    def __init__(self, ticket):
        self._ticket = ticket
        self.appended = []

    async def get_ticket(self, ticket_id):
        return self._ticket if self._ticket and self._ticket["id"] == ticket_id else None

    async def list_events(self, ticket_id):
        return []

    async def list_evidence(self, ticket_id):
        return []

    async def append_event(self, **kwargs):
        self.appended.append(kwargs)


class FakeConversationStore:
    def __init__(self, conversation):
        self._conversation = conversation

    async def get_conversation(self, conv_id, user_id=None):
        return self._conversation


class FakeQueryLogStore:
    async def get_by_conversation(self, conv_id):
        return []


class FakeRetriever:
    def __init__(self, items):
        self._items = items
        self.calls = []

    def retrieve(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return self._items


def _ticket(**overrides) -> dict:
    ticket = {
        "id": "tk-1",
        "ticket_number": "T-20260926-001",
        "conversation_id": "conv-1",
        "title": "无人机图传黑屏",
        "problem_summary": "用户问题：Mini 4 Pro 图传黑屏；初步建议：重启尝试",
        "device_model": "mini_4_pro",
        "fault_category": "transmission_abnormal",
        "safety_level": "none",
        "status": "submitted",
    }
    ticket.update(overrides)
    return ticket


def _evidence() -> list[dict]:
    return [
        {
            "id": "doc:chunk:0",
            "content": "图传黑屏时先检查天线与固件版本。",
            "source": "troubleshooting/firmware.md",
            "title": "固件异常排查",
            "document_type": "troubleshooting",
            "product_model": "mini_4_pro",
            "data_type": "factual",
            "score": 0.82,
        },
        {
            "id": "sop:chunk:0",
            "content": "SOP：固件升级标准流程……",
            "source": "sop/firmware_upgrade.md",
            "title": "固件升级 SOP",
            "document_type": "sop",
            "product_model": "mini_4_pro",
            "data_type": "factual",
            "score": 0.7,
        },
    ]


def _structured_analysis(**overrides) -> dict:
    analysis = {
        "summary": "图传黑屏疑似固件或天线问题",
        "product_model": "mini_4_pro",
        "possible_causes": [
            {"cause": "固件异常", "status": "knowledge_based", "evidence_ids": ["doc:chunk:0"]}
        ],
        "recommended_steps": [{"step": "检查固件版本", "expected": "版本一致"}],
        "needs_human_service": False,
        "confidence": 0.8,
        "citations": [
            {"evidence_id": "doc:chunk:0", "document_name": "firmware.md", "data_type": "factual"},
            {"evidence_id": "hallucinated", "document_name": "fake.md"},
        ],
        "handling_advice": ["先远程指导用户检查固件", "无效则安排检测"],
        "suggested_reply": "您好，建议先重启并检查固件版本……",
        "risk_flags": [],
    }
    analysis.update(overrides)
    return analysis


def _service(ticket, retriever_items=None) -> tuple[TicketAnalysisService, FakeTicketStore, FakeRetriever]:
    ticket_store = FakeTicketStore(ticket)
    retriever = FakeRetriever(retriever_items if retriever_items is not None else _evidence())
    service = TicketAnalysisService(
        ticket_store=ticket_store,
        conversation_store=FakeConversationStore({"id": "conv-1", "messages": [
            {"role": "user", "content": "Mini 4 Pro 图传黑屏怎么办"},
            {"role": "assistant", "content": "先重启尝试"},
        ]}),
        query_log_store=FakeQueryLogStore(),
        rag_retriever=retriever,
    )
    return service, ticket_store, retriever


@pytest.mark.asyncio
async def test_analyze_happy_path_persists_agent_suggestion(monkeypatch):
    service, ticket_store, retriever = _service(_ticket())
    monkeypatch.setattr(
        "app.services.ticket_analysis_service.call_llm",
        _fake_llm(_structured_analysis()),
    )

    analysis = await service.analyze("tk-1")

    assert analysis["ticket_number"] == "T-20260926-001"
    assert analysis["product_model"] == "mini_4_pro"
    assert analysis["summary"].startswith("图传黑屏")
    # 证据投影不带正文；SOP 单独归组
    assert all("content" not in item for item in analysis["knowledge"])
    assert [item["document_type"] for item in analysis["sop_recommendations"]] == ["sop"]
    assert analysis["handling_advice"] == ["先远程指导用户检查固件", "无效则安排检测"]
    # 引用校验：非法 citation 被丢弃
    assert [c["evidence_id"] for c in analysis["diagnosis"]["citations"]] == ["doc:chunk:0"]
    # 事件持久化：agent 角色 + agent_suggestion 类型
    assert len(ticket_store.appended) == 1
    event = ticket_store.appended[0]
    assert event["actor_type"] == "agent"
    assert event["event_type"] == "agent_suggestion"
    assert event["metadata"]["suggested_reply"].startswith("您好")
    # 检索器被复用且带机型硬过滤约束
    assert retriever.calls[0]["metadata_constraints"]["product_model"] == "mini_4_pro"


@pytest.mark.asyncio
async def test_analyze_high_risk_uses_conservative_advice(monkeypatch):
    service, ticket_store, _ = _service(_ticket(safety_level="high"))
    monkeypatch.setattr(
        "app.services.ticket_analysis_service.call_llm",
        _fake_llm(_structured_analysis(handling_advice=["建议用户自行拆机检查"], suggested_reply="拆机吧")),
    )

    analysis = await service.analyze("tk-1")

    assert analysis["high_risk"] is True
    assert "ticket_safety_level_high" in analysis["risk_flags"]
    # LLM 的危险建议被保守清单覆盖
    assert analysis["handling_advice"] == CONSERVATIVE_HANDLING_ADVICE
    assert analysis["suggested_reply"] == CONSERVATIVE_REPLY_TEMPLATE.format(
        summary="用户问题：Mini 4 Pro 图传黑屏；初步建议：重启尝试"[:120]
    )
    assert any("不得作为确诊依据" not in d for d in analysis["disclaimers"])


@pytest.mark.asyncio
async def test_analyze_diagnosis_failure_degrades_to_conservative(monkeypatch):
    """诊断 LLM 失败 → analysis 仍返回（diagnosis=None），回复走保守模板。"""
    service, ticket_store, _ = _service(_ticket())

    async def _boom(**kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr("app.services.ticket_analysis_service.call_llm", _boom)
    analysis = await service.analyze("tk-1")

    assert analysis["diagnosis"] is None
    assert analysis["confidence"] == 0.0
    assert "low_confidence" in analysis["risk_flags"]
    assert analysis["suggested_reply"].startswith("您好")
    assert len(ticket_store.appended) == 1


@pytest.mark.asyncio
async def test_analyze_all_invalid_citations_zeroes_confidence(monkeypatch):
    structured = _structured_analysis(citations=[{"evidence_id": "made-up", "document_name": "x.md"}])
    service, _, _ = _service(_ticket())
    monkeypatch.setattr(
        "app.services.ticket_analysis_service.call_llm", _fake_llm(structured)
    )
    analysis = await service.analyze("tk-1")
    assert analysis["diagnosis"]["citations"] == []
    assert analysis["diagnosis"]["confidence"] == 0.0
    assert "low_confidence" in analysis["risk_flags"]


@pytest.mark.asyncio
async def test_analyze_profile_falls_back_to_llm(monkeypatch):
    """快照与 query_log 均无机型 → 走一次 LLM 补全画像。"""
    ticket = _ticket(device_model=None, fault_category=None)
    service, _, retriever = _service(ticket)
    monkeypatch.setattr(
        "app.services.ticket_analysis_service.call_llm",
        _fake_llm(_structured_analysis()),
    )
    analysis = await service.analyze("tk-1")
    assert analysis["profile_source"] == "llm_fallback"
    assert analysis["product_model"] == "mini_4_pro"


@pytest.mark.asyncio
async def test_analyze_unknown_ticket_raises():
    service, _, _ = _service(_ticket())
    with pytest.raises(LookupError):
        await service.analyze("missing")


def _fake_llm(structured: dict):
    class _FakeLLM:
        def __init__(self, *args, **kwargs):
            pass

        async def __call__(self, **kwargs):
            return {"text": "", "structured": structured}

    async def _call(**kwargs):
        return {"text": "", "structured": structured}

    return _call
