from app.graph.state import AgentState, JudgeResult
from typing import get_type_hints, get_args

def test_agent_state_has_required_fields():
    hints = get_type_hints(AgentState)
    required = ["query", "conversation_id", "history", "rewritten_query",
                "needs_decomposition", "is_relevant", "retrieval_result",
                "rag_quality_pass", "web_search_result", "local_answer",
                "online_answer", "hallucination_flag", "answer_quality_pass",
                "final_answer", "route_path", "judge_log"]
    for field in required:
        assert field in hints, f"Missing field: {field}"

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
