from app.graph.state import AgentState, JudgeResult
from typing import get_type_hints, get_args

def test_agent_state_has_required_fields():
    hints = get_type_hints(AgentState)
    required = ["query", "conversation_id", "history", "rewritten_query",
                "is_relevant", "retrieval_result",
                "rag_quality_pass", "web_search_result",
                "has_hallucination", "answer_quality_pass",
                "final_answer", "route_path", "judge_log"]
    for field in required:
        assert field in hints, f"Missing field: {field}"


def test_agent_state_has_p0_p1_fields():
    """P0-2/P1-2/P1-3/P1-5 新增字段验证。"""
    hints = get_type_hints(AgentState)
    # P0-2: 多步推理恢复
    assert "needs_decomposition" in hints
    assert "reasoning_steps" in hints
    # P1-5: 闲聊快速通道
    assert "is_chitchat" in hints
    # P1-2: reranker 分数阈值
    assert "avg_reranker_score" in hints
    # P1-3: 质量警告
    assert "quality_warning" in hints


def test_agent_state_no_legacy_fields():
    """验证真正已删除的 legacy 字段不存在。"""
    hints = get_type_hints(AgentState)
    for legacy in [
        "hallucination_flag", "fallback_count",
        "local_answer", "online_answer",
    ]:
        assert legacy not in hints, f"{legacy} should be removed"


def test_judge_result_structure():
    jr: JudgeResult = {"judge_type": "is_relevant", "passed": True, "raw_output": {}}
    assert jr["passed"] is True
    assert jr["judge_type"] == "is_relevant"

def test_judge_log_uses_add_reducer():
    """验证 judge_log 字段有 Annotated[..., add] 标记。"""
    hints = get_type_hints(AgentState, include_extras=True)
    judge_log_hint = hints.get("judge_log")
    # Annotated 类型会有 __metadata__
    assert judge_log_hint is not None
    assert hasattr(judge_log_hint, "__metadata__"), "judge_log should be Annotated[list, add]"
