# backend/tests/unit/test_followup.py
"""阶段 3：信息充分性判断与主动追问快速通道。

覆盖 target_architecture.md §5.1 守卫矩阵的九类场景 + ask_followup 节点行为 +
decompose_question 新字段提取 + builder 路由分支 + get_history route_path。
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.graph.builder import route_after_decompose
from app.graph.nodes import (
    _should_followup,
    ask_followup_node,
    decompose_question_node,
)
from app.graph.state import AgentState


# ---------------------------------------------------------------------------
# _should_followup 守卫矩阵
# ---------------------------------------------------------------------------
def _base_followup_state(**overrides) -> dict:
    """构造"应当追问"的基准状态，再按 overrides 逐项破坏条件。"""
    state = {
        "query": "我的无人机飞不了了",
        "intent": "troubleshooting",
        "information_sufficient": False,
        "information_gaps": [{"field": "product_model", "reason": "无法确定具体型号"}],
        "safety_level": "none",
        "safety_flag": False,
        "followup_just_asked": False,
        "user_requests_human": False,
        "prior_troubleshoot_failed": False,
        "needs_decomposition": False,
        "attachment_evidence": [],
    }
    state.update(overrides)
    return state


def test_should_followup_when_info_insufficient():
    """任务书场景 1：'我的无人机飞不了了' → 允许追问。"""
    assert _should_followup(_base_followup_state()) is True


def test_should_not_followup_when_info_sufficient():
    """任务书场景 2：信息完整 → 不追问。"""
    assert _should_followup(_base_followup_state(information_sufficient=True)) is False


def test_should_not_followup_when_not_evaluated():
    """LLM 未给出充分性判断（None）→ 保守不追问。"""
    assert _should_followup(_base_followup_state(information_sufficient=None)) is False


def test_should_not_followup_when_high_risk():
    """任务书场景 3：高风险永不追问，必须立即给保守指引。"""
    assert _should_followup(_base_followup_state(safety_level="high")) is False
    assert _should_followup(_base_followup_state(safety_flag=True)) is False


def test_should_not_followup_when_user_requests_human():
    """任务书场景 4：用户要求人工 → 不追问。"""
    assert _should_followup(_base_followup_state(user_requests_human=True)) is False


def test_should_not_followup_when_prior_troubleshoot_failed():
    """任务书场景 5：已排查失败 → 不追问（直接升级）。"""
    assert _should_followup(_base_followup_state(prior_troubleshoot_failed=True)) is False


def test_should_not_followup_when_just_asked():
    """任务书场景 6：上一轮刚追问过 → 不得连环追问。"""
    assert _should_followup(_base_followup_state(followup_just_asked=True)) is False


def test_should_not_followup_when_attachment_present():
    """任务书场景 7：用户已附材料 → 视为已尽力提供，不追问。"""
    evidence = [{"id": "att-1", "content": "日志内容"}]
    assert _should_followup(_base_followup_state(attachment_evidence=evidence)) is False


def test_should_not_followup_when_chitchat_intent():
    """任务书场景 8：闲聊/非诊断意图 → 不追问。"""
    assert _should_followup(_base_followup_state(intent="chitchat")) is False
    assert _should_followup(_base_followup_state(intent="product_parameter")) is False


def test_should_not_followup_when_needs_decomposition():
    """任务书场景 9：多步问题 → 走分解路径，不追问。"""
    assert _should_followup(_base_followup_state(needs_decomposition=True)) is False


def test_should_not_followup_when_gaps_empty():
    """声称不足却给不出缺口 → 不追问（追问必须言之有物）。"""
    assert _should_followup(_base_followup_state(information_gaps=[])) is False


def test_flight_safety_intent_eligible():
    """飞行安全意图（非高风险）也可追问。"""
    assert _should_followup(_base_followup_state(intent="flight_safety")) is True


# ---------------------------------------------------------------------------
# route_after_decompose 分支
# ---------------------------------------------------------------------------
def test_route_decompose_to_followup_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_FOLLOWUP_ENABLED", True)
    assert route_after_decompose(_base_followup_state()) == "ask_followup"


def test_route_decompose_never_followup_when_disabled(monkeypatch):
    """开关关闭（默认）→ 行为与改造前完全一致。"""
    monkeypatch.setattr(settings, "AGENT_FOLLOWUP_ENABLED", False)
    assert route_after_decompose(_base_followup_state()) == "judge_relevance"


def test_route_decompose_high_risk_overrides_followup(monkeypatch):
    """高风险覆盖一切快速通道：即使信息不足也走 judge_relevance 检索安全知识。"""
    monkeypatch.setattr(settings, "AGENT_FOLLOWUP_ENABLED", True)
    state = _base_followup_state(safety_level="high")
    assert route_after_decompose(state) == "judge_relevance"


def test_route_decompose_chitchat_priority_before_followup(monkeypatch):
    """闲聊路径优先于追问（闲聊没有 information_sufficient 评估也不会追问）。"""
    monkeypatch.setattr(settings, "AGENT_FOLLOWUP_ENABLED", True)
    state = _base_followup_state(is_chitchat=True)
    assert route_after_decompose(state) == "chitchat_node"


def test_route_decompose_multistep_after_followup_guard(monkeypatch):
    """needs_decomposition=true 时守卫不通过 → 走多步推理。"""
    monkeypatch.setattr(settings, "AGENT_FOLLOWUP_ENABLED", True)
    state = _base_followup_state(
        needs_decomposition=True,
        reasoning_steps=[{"sub_query": "图传距离是多少"}],
    )
    assert route_after_decompose(state) == "multi_step_reason"


# ---------------------------------------------------------------------------
# ask_followup_node
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ask_followup_node_output_shape():
    """追问节点：流式生成追问，route_path/recommended_action=followup，不升级。"""
    state = AgentState(
        query="我的无人机飞不了了",
        conversation_id="c1",
        history=[{"role": "user", "content": "我的无人机飞不了了"}],
        information_gaps=[
            {"field": "product_model", "reason": "无法确定具体型号"},
            {"field": "symptoms", "reason": "只描述了'飞不了了'"},
        ],
        intent="troubleshooting",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "请问你的无人机是哪个型号？具体有什么表现？", "structured": None}
        result = await ask_followup_node(state, None)

    assert result["route_path"] == "followup"
    assert result["recommended_action"] == "followup"
    assert result["escalation_required"] is False
    assert "型号" in result["final_answer"]
    assert mock_llm.call_args.kwargs["stream"] is True
    # 追问提示词必须带上缺口清单
    assert "product_model" in mock_llm.call_args.kwargs["system_prompt"]
    # 追问不检索、不诊断：judge_log 记录充分性判断
    assert result["judge_log"][0]["judge_type"] == "information_sufficiency"


@pytest.mark.asyncio
async def test_ask_followup_node_fallback_on_llm_error():
    """LLM 失败 → 静态追问兜底，路由语义不变。"""
    state = AgentState(
        query="飞不了了",
        conversation_id="c1",
        history=[],
        information_gaps=[{"field": "product_model", "reason": "型号未知"}],
        intent="troubleshooting",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("超时")
        result = await ask_followup_node(state, None)

    assert result["route_path"] == "followup"
    assert result["recommended_action"] == "followup"
    assert result["final_answer"]  # 有兜底文本
    assert "型号" in result["final_answer"]


# ---------------------------------------------------------------------------
# decompose_question_node 新字段提取
# ---------------------------------------------------------------------------
def _decompose_structured(**extra) -> dict:
    structured = {
        "is_chitchat": False,
        "needs_decomposition": False,
        "reasoning_steps": [],
        "intent": "troubleshooting",
        "product_model": None,
        "component": "battery",
        "fault_type": None,
        "safety_flag": False,
        "safety_level": "none",
        "safety_situation": "unknown",
        "user_requests_human": False,
        "information_sufficient": False,
        "information_gaps": [
            {"field": "product_model", "reason": "未说明机型"},
            {"bad": "entry"},                       # 非法条目应被丢弃
            {"field": "", "reason": "空字段丢弃"},
        ],
        "symptoms": ["指示灯闪烁", " ", "无法起飞"],
    }
    structured.update(extra)
    return structured


@pytest.mark.asyncio
async def test_decompose_extracts_sufficiency_and_profile():
    state = AgentState(query="电池充不上电", conversation_id="c1", history=[], rewritten_query="无人机电池充不上电", judge_log=[])
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": _decompose_structured()}
        result = await decompose_question_node(state)

    assert result["information_sufficient"] is False
    # 非法缺口被清洗，只剩合法条目
    assert result["information_gaps"] == [{"field": "product_model", "reason": "未说明机型"}]
    # issue_profile 与 metadata_constraints 同源
    assert result["issue_profile"]["component"] == result["metadata_constraints"]["component"]
    assert result["issue_profile"]["symptoms"] == ["指示灯闪烁", "无法起飞"]
    assert result["issue_profile"]["situation"] is None  # 非高风险时 situation 为 None


@pytest.mark.asyncio
async def test_decompose_insufficient_without_gaps_becomes_sufficient():
    """声称不足但给不出缺口 → 保守视为充分（不允许空转一轮追问）。"""
    state = AgentState(query="无人机异常", conversation_id="c1", history=[], rewritten_query="无人机异常", judge_log=[])
    structured = _decompose_structured(information_gaps=[])
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": structured}
        result = await decompose_question_node(state)

    assert result["information_sufficient"] is True
    assert result["information_gaps"] == []


@pytest.mark.asyncio
async def test_decompose_high_risk_forces_flight_safety_intent():
    """安全判断优先：高风险时 intent 强制 flight_safety，situation 进 issue_profile。"""
    state = AgentState(query="电池鼓包了", conversation_id="c1", history=[], rewritten_query="电池鼓包了怎么办", judge_log=[])
    structured = _decompose_structured(
        intent="troubleshooting",
        safety_flag=True,
        safety_level="high",
        safety_situation="charging",
        information_sufficient=True,
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": structured}
        result = await decompose_question_node(state)

    assert result["intent"] == "flight_safety"
    assert result["issue_profile"]["situation"] == "charging"


@pytest.mark.asyncio
async def test_decompose_llm_failure_stays_conservative():
    """decompose LLM 失败 → 不产出充分性字段（None），追问守卫必然不通过。"""
    state = AgentState(query="无人机飞不了了", conversation_id="c1", history=[], judge_log=[])
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("LLM 不可用")
        result = await decompose_question_node(state)

    assert result.get("information_sufficient") is None
    assert "information_gaps" not in result or not result.get("information_gaps")
    # 保守兜底下不允许追问
    monkey_state = dict(result)
    monkey_state["followup_just_asked"] = False
    assert _should_followup(monkey_state) is False


# ---------------------------------------------------------------------------
# get_history 附带 route_path（追问守卫数据源）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_history_returns_route_path():
    from app.services.conversation_store import ConversationStore

    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = ConversationStore(db_path)
        await store.init()
        conv_id = await store.create_conversation()
        await store.add_message(conv_id, role="user", content="飞不了了")
        await store.add_message(conv_id, role="assistant", content="请确认型号", route_path="followup")
        await store.add_message(conv_id, role="user", content="Mini 4 Pro，开不了机")
        history = await store.get_history(conv_id, limit=10)
        assert history[-1]["route_path"] is None           # 新 user 消息无 route
        assert history[-2]["route_path"] == "followup"     # 上一轮 assistant 是追问
    finally:
        os.unlink(db_path)
