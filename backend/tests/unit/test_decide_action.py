# backend/tests/unit/test_decide_action.py
"""阶段 4：decide_action 确定性业务决策阶梯（零 LLM）。

覆盖 G0 全部升级触发与 auto_create_ticket 边界、G1 透传、G2 双门槛、G3 默认，
以及 judge_log 记录与 escalation_required 一致性。
"""
import pytest

from app.graph.nodes import (
    DIAGNOSIS_LOW_CONFIDENCE,
    TICKET_CONFIDENCE_THRESHOLD,
    decide_action_node,
)


def _good_diagnosis(**overrides) -> dict:
    diagnosis = {
        "summary": "图传黑屏，疑似硬件损坏",
        "product_model": "mini_4_pro",
        "needs_human_service": True,
        "confidence": 0.7,
        "citations": [{"evidence_id": "doc:chunk:0", "document_name": "a.md"}],
    }
    diagnosis.update(overrides)
    return diagnosis


def _g2_state(**overrides) -> dict:
    """构造"命中 G2 create_ticket"的基准状态，再按 overrides 破坏条件。"""
    state = {
        "route_path": "local",
        "intent": "troubleshooting",
        "information_sufficient": True,
        "diagnosis": _good_diagnosis(),
        "avg_reranker_score": 0.8,
        "retrieval_result": [{"id": "doc:chunk:0", "content": "证据正文"}],
        "safety_level": "none",
        "safety_flag": False,
        "user_requests_human": False,
        "prior_troubleshoot_failed": False,
        "has_hallucination": False,
        "answer_quality_pass": True,
        "judge_log": [],
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# G2：create_ticket（先验证默认命中，再逐项破坏）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_g2_creates_ticket_when_service_needed_and_confident():
    result = await decide_action_node(_g2_state())
    assert result["recommended_action"] == "create_ticket"
    assert result["auto_create_ticket"] is True
    assert result["escalation_required"] is False
    assert result["judge_log"][0]["judge_type"] == "decide_action"
    assert result["judge_log"][0]["raw_output"]["action"] == "create_ticket"


@pytest.mark.asyncio
async def test_g2_blocked_at_confidence_boundary():
    """confidence 恰低于 0.55 → 不建单（降级 answer）。"""
    result = await decide_action_node(_g2_state(diagnosis=_good_diagnosis(confidence=0.54)))
    assert result["recommended_action"] == "answer"
    assert result["auto_create_ticket"] is False


@pytest.mark.asyncio
async def test_g2_blocked_when_needs_human_service_false():
    result = await decide_action_node(_g2_state(diagnosis=_good_diagnosis(needs_human_service=False)))
    assert result["recommended_action"] == "answer"


@pytest.mark.asyncio
async def test_g2_blocked_when_intent_not_diagnostic():
    """参数/原理类问题即便 needs_human_service=true 也不建单。"""
    result = await decide_action_node(_g2_state(intent="product_parameter"))
    assert result["recommended_action"] == "answer"


@pytest.mark.asyncio
async def test_g2_blocked_when_information_insufficient():
    result = await decide_action_node(_g2_state(information_sufficient=None))
    assert result["recommended_action"] == "answer"


@pytest.mark.asyncio
async def test_g2_blocked_on_non_local_route():
    """联网路径无诊断结构 → 不满足 G2，落回 answer（证据可用、无升级触发）。"""
    result = await decide_action_node(
        _g2_state(route_path="online", web_search_result=[{"id": "web:1", "content": "结果"}])
    )
    assert result["recommended_action"] == "answer"


@pytest.mark.asyncio
async def test_g2_blocked_when_hallucination_detected():
    result = await decide_action_node(_g2_state(has_hallucination=True))
    assert result["recommended_action"] == "answer"


@pytest.mark.asyncio
async def test_g2_blocked_when_quality_failed():
    result = await decide_action_node(_g2_state(answer_quality_pass=False))
    assert result["recommended_action"] == "answer"


# ---------------------------------------------------------------------------
# G0：escalate 触发与 auto_create_ticket 边界
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_g0_user_requests_human_auto_creates_ticket():
    result = await decide_action_node(_g2_state(user_requests_human=True))
    assert result["recommended_action"] == "escalate"
    assert result["auto_create_ticket"] is True
    assert result["escalation_required"] is True
    assert "user_requests_human" in result["judge_log"][0]["raw_output"]["triggered_rules"]


@pytest.mark.asyncio
async def test_g0_prior_troubleshoot_failed_auto_creates_ticket():
    result = await decide_action_node(_g2_state(prior_troubleshoot_failed=True))
    assert result["recommended_action"] == "escalate"
    assert result["auto_create_ticket"] is True
    assert "prior_troubleshoot_failed" in result["judge_log"][0]["raw_output"]["triggered_rules"]


@pytest.mark.asyncio
async def test_g0_high_risk_never_auto_creates_ticket():
    """高风险首轮：升级但不自动建单（可能只是安全咨询，按钮留给用户）。"""
    result = await decide_action_node(_g2_state(safety_level="high"))
    assert result["recommended_action"] == "escalate"
    assert result["auto_create_ticket"] is False
    assert result["escalation_required"] is True
    assert "high_risk" in result["judge_log"][0]["raw_output"]["triggered_rules"]


@pytest.mark.asyncio
async def test_g0_diagnosis_missing_escalates():
    result = await decide_action_node(_g2_state(diagnosis=None))
    assert result["recommended_action"] == "escalate"
    assert result["auto_create_ticket"] is False
    assert any(r.startswith("diagnosis_missing") for r in result["judge_log"][0]["raw_output"]["triggered_rules"])


@pytest.mark.asyncio
async def test_g0_diagnosis_confidence_low_escalates():
    result = await decide_action_node(
        _g2_state(diagnosis=_good_diagnosis(confidence=DIAGNOSIS_LOW_CONFIDENCE - 0.01))
    )
    assert result["recommended_action"] == "escalate"


@pytest.mark.asyncio
async def test_g0_reranker_low_escalates():
    result = await decide_action_node(_g2_state(avg_reranker_score=0.3))
    assert result["recommended_action"] == "escalate"


@pytest.mark.asyncio
async def test_g0_no_valid_evidence_escalates():
    result = await decide_action_node(_g2_state(retrieval_result=[]))
    assert result["recommended_action"] == "escalate"


@pytest.mark.asyncio
async def test_g0_online_search_failed_escalates():
    """联网路径：搜索失败即无法可靠回答 → 升级；不检查 diagnosis（该路径无诊断）。"""
    state = _g2_state(route_path="online", web_search_result=[])
    result = await decide_action_node(state)
    assert result["recommended_action"] == "escalate"


@pytest.mark.asyncio
async def test_online_with_valid_evidence_not_escalated():
    """联网路径有可用证据且无其他触发 → answer（不因 diagnosis 缺失误升级）。"""
    state = _g2_state(
        route_path="online",
        web_search_result=[{"id": "web:1", "content": "官方公告"}],
    )
    result = await decide_action_node(state)
    assert result["recommended_action"] == "answer"
    assert result["escalation_required"] is False


@pytest.mark.asyncio
async def test_g0_decomposition_empty_context_escalates():
    state = _g2_state(route_path="decomposition", retrieval_result=[])
    result = await decide_action_node(state)
    assert result["recommended_action"] == "escalate"


@pytest.mark.asyncio
async def test_g0_safety_flag_only_also_escalates():
    result = await decide_action_node(_g2_state(safety_flag=True))
    assert result["recommended_action"] == "escalate"


# ---------------------------------------------------------------------------
# G1 / G3
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_g1_followup_passthrough():
    result = await decide_action_node({"route_path": "followup", "judge_log": []})
    assert result["recommended_action"] == "followup"
    assert result["auto_create_ticket"] is False
    assert result["escalation_required"] is False


@pytest.mark.asyncio
async def test_g3_answer_default_for_non_diagnostic_intent():
    """参数类问题、证据充分、质量通过 → 默认 answer。"""
    state = _g2_state(
        intent="product_parameter",
        diagnosis=_good_diagnosis(needs_human_service=False),
    )
    result = await decide_action_node(state)
    assert result["recommended_action"] == "answer"
    assert result["escalation_required"] is False


# ---------------------------------------------------------------------------
# 阈值常量与设计一致
# ---------------------------------------------------------------------------
def test_thresholds_match_design():
    """阈值与 target_architecture.md §5.3 一致（防无意识漂移）。"""
    assert DIAGNOSIS_LOW_CONFIDENCE == 0.4
    assert TICKET_CONFIDENCE_THRESHOLD == 0.55
