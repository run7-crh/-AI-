# backend/tests/unit/test_trace.py
"""trace 纯函数单测：白名单提取 / 截断 / reasoning 捞取。"""
from app.api.trace import (
    extract_reasoning_content,
    extract_trace_output,
    truncate_text,
)


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert truncate_text("短文本") == "短文本"

    def test_long_text_truncated_with_ellipsis(self):
        out = truncate_text("x" * 300)
        assert len(out) == 201  # 200 字 + 省略号
        assert out.endswith("…")

    def test_non_string_returned_as_is(self):
        assert truncate_text(123) == 123  # type: ignore[arg-type]


class TestExtractTraceOutput:
    def test_whitelist_filters_unknown_fields(self):
        output = {"rewritten_query": "什么是 RAG", "is_relevant": True, "judge_log": []}
        assert extract_trace_output("rewrite_query", output) == {
            "rewritten_query": "什么是 RAG"
        }

    def test_generate_nodes_return_empty(self):
        # 正文走 token 流，仅显示名称+耗时
        assert extract_trace_output(
            "generate_local", {"final_answer": "x", "route_path": "local"}
        ) == {}
        assert extract_trace_output("multi_step_reason", {"final_answer": "x"}) == {}
        assert extract_trace_output("chitchat_node", {"final_answer": "x"}) == {}
        assert extract_trace_output("generate_online", {"final_answer": "x"}) == {}

    def test_unknown_node_returns_empty(self):
        assert extract_trace_output("nonexistent_node", {"a": 1}) == {}

    def test_none_or_empty_output_returns_empty(self):
        assert extract_trace_output("rewrite_query", None) == {}
        assert extract_trace_output("rewrite_query", {}) == {}

    def test_truncates_retrieval_result_content(self):
        output = {
            "retrieval_result": [
                {"content": "x" * 300, "title": "RAG", "source": "a.md", "score": 0.9}
            ],
            "avg_reranker_score": 0.9,
        }
        result = extract_trace_output("rag_retrieve", output)
        assert len(result["retrieval_result"][0]["content"]) == 201
        assert result["avg_reranker_score"] == 0.9
        # 截断不改其他字段
        assert result["retrieval_result"][0]["title"] == "RAG"

    def test_truncates_web_search_result_content(self):
        output = {"web_search_result": [{"content": "y" * 300, "title": "t"}]}
        result = extract_trace_output("web_search", output)
        assert len(result["web_search_result"][0]["content"]) == 201

    def test_truncates_reasoning_steps_strings(self):
        output = {
            "needs_decomposition": True,
            "reasoning_steps": ["z" * 300, "短问题"],
        }
        result = extract_trace_output("decompose_question", output)
        assert len(result["reasoning_steps"][0]) == 201
        assert result["reasoning_steps"][1] == "短问题"

    def test_judge_log_takes_last_entry_only(self):
        # judge_log 是 add reducer 累积的，只下发当前节点的最后一条
        output = {
            "rag_quality_pass": False,
            "judge_log": [
                {"judge_type": "is_relevant", "passed": True},
                {
                    "judge_type": "is_retrieval_quality",
                    "passed": False,
                    "raw_output": {"reason": "low reranker score"},
                },
            ],
        }
        result = extract_trace_output("rag_quality_eval", output)
        assert result["rag_quality_pass"] is False
        assert result["judge_log"]["judge_type"] == "is_retrieval_quality"

    def test_missing_whitelisted_field_skipped(self):
        # 节点异常退回路径只返回部分字段
        assert extract_trace_output("query_corrector", {"correction_count": 1}) == {
            "correction_count": 1
        }

    def test_combined_quality_check_fields(self):
        output = {
            "has_hallucination": False,
            "answer_quality_pass": True,
            "judge_log": [{"judge_type": "combined_quality", "passed": True}],
        }
        result = extract_trace_output("combined_quality_check", output)
        assert set(result.keys()) == {
            "has_hallucination",
            "answer_quality_pass",
            "judge_log",
        }


class TestExtractReasoningContent:
    def test_from_object_additional_kwargs(self):
        class FakeChunk:
            additional_kwargs = {"reasoning_content": "思考中"}

        assert extract_reasoning_content(FakeChunk()) == "思考中"

    def test_from_object_empty_kwargs(self):
        class FakeChunk:
            additional_kwargs = {}

        assert extract_reasoning_content(FakeChunk()) == ""

    def test_from_dict_additional_kwargs(self):
        chunk = {"content": "答", "additional_kwargs": {"reasoning_content": "思"}}
        assert extract_reasoning_content(chunk) == "思"

    def test_from_dict_top_level_fallback(self):
        chunk = {"content": "答", "reasoning_content": "思"}
        assert extract_reasoning_content(chunk) == "思"

    def test_missing_returns_empty(self):
        assert extract_reasoning_content({"content": "x"}) == ""
        assert extract_reasoning_content("not-a-chunk") == ""
        assert extract_reasoning_content(None) == ""

    def test_object_without_kwargs_attr(self):
        class FakeChunk:
            content = "x"

        assert extract_reasoning_content(FakeChunk()) == ""
