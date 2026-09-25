import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.graph.tools import call_llm, evaluate, _estimate_tokens, _truncate_history
from pydantic import BaseModel


class JudgeSchema(BaseModel):
    passed: bool
    reason: str

@pytest.mark.asyncio
async def test_call_llm_returns_text():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "测试回复"
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        result = await call_llm("system", "user", temperature=0.5)
    assert result["text"] == "测试回复"
    assert result["structured"] is None

@pytest.mark.asyncio
async def test_call_llm_with_history_passes_messages():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "回复"
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        await call_llm("system", "user", history=[{"role": "user", "content": "历史"}])
    mock_llm.ainvoke.assert_called_once()
    msgs = mock_llm.ainvoke.call_args.args[0]
    assert len(msgs) >= 3  # system + history + user

@pytest.mark.asyncio
async def test_call_llm_with_schema_returns_structured():
    from pydantic import BaseModel
    class TestSchema(BaseModel):
        passed: bool
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.passed = True
    mock_structured.model_dump = MagicMock(return_value={"passed": True})
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(return_value=mock_structured)
    mock_llm.with_structured_output = MagicMock(return_value=structured_llm)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        result = await call_llm("system", "user", output_schema=TestSchema)
    assert result["structured"]["passed"] is True


@pytest.mark.asyncio
async def test_call_llm_stream_failure_is_not_retried_after_partial_stream():
    """A failed stream must not restart and duplicate already emitted tokens."""
    attempts = 0

    class FailingStreamLLM:
        def __init__(self):
            self.astream = self._astream

        async def _astream(self, messages, config=None):
            nonlocal attempts
            attempts += 1
            yield type("Chunk", (), {"content": "部分"})()
            raise RuntimeError("连接中断")

    mock_llm = FailingStreamLLM()
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        with pytest.raises(RuntimeError, match="连接中断"):
            await call_llm("system", "user", stream=True)

    assert attempts == 1


@pytest.mark.asyncio
async def test_evaluate_is_relevant_returns_passed_true():
    mock_structured = MagicMock()
    mock_structured.passed = True
    mock_structured.reason = "相关问题"
    mock_structured.model_dump = MagicMock(return_value={"passed": True, "reason": "相关问题"})
    mock_llm = MagicMock()
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(return_value=mock_structured)
    mock_llm.with_structured_output = MagicMock(return_value=structured_llm)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        result = await evaluate(judge_type="is_relevant", source="", query="什么是 RAG？")
    assert result["passed"] is True
    assert result["judge_type"] == "is_relevant"
    assert "reason" in result["raw_output"]

@pytest.mark.asyncio
async def test_evaluate_uses_temp_0_2_regardless_of_input():
    """验证评估温度统一为 0.2（修复设计问题 2）。"""
    mock_structured = MagicMock()
    mock_structured.passed = False
    mock_structured.reason = "原因"
    mock_structured.model_dump = MagicMock(return_value={"passed": False, "reason": "原因"})
    mock_llm = MagicMock()
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(return_value=mock_structured)
    mock_llm.with_structured_output = MagicMock(return_value=structured_llm)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm) as mock_cls:
        await evaluate(judge_type="is_relevant", source="x", answer="y", query="z")
    assert mock_cls.call_args.kwargs["temperature"] == 0.2

@pytest.mark.asyncio
async def test_evaluate_invalid_judge_type_raises():
    with pytest.raises(ValueError):
        await evaluate(judge_type="invalid_type", source="x")


from app.graph.tools import retrieve, tavily_search


@pytest.mark.asyncio
async def test_retrieve_calls_rag_retriever():
    mock_retriever = MagicMock()
    mock_retriever.final_top_k = 3
    mock_retriever.retrieve = MagicMock(return_value=[
        {"content": "x", "source": "a.md", "title": "A", "score": 0.9}
    ])
    result = await retrieve("测试", mock_retriever, top_k=3)
    mock_retriever.retrieve.assert_called_once_with("测试", top_k=3)
    assert result[0]["content"] == "x"


@pytest.mark.asyncio
async def test_retrieve_forwards_non_default_top_k():
    """Routing's top-1 relevance probe must reach the retriever."""
    mock_retriever = MagicMock()
    mock_retriever.final_top_k = 3
    mock_retriever.retrieve = MagicMock(return_value=[])
    await retrieve("测试", mock_retriever, top_k=1)
    mock_retriever.retrieve.assert_called_once_with("测试", top_k=1)


@pytest.mark.asyncio
async def test_retrieve_supports_legacy_query_only_retriever():
    """Adapters predating request-scoped top_k remain usable."""
    class QueryOnlyRetriever:
        def retrieve(self, query):
            return [{"content": query}]

    result = await retrieve("测试", QueryOnlyRetriever(), top_k=1)
    assert result == [{"content": "测试"}]

@pytest.mark.asyncio
async def test_tavily_search_returns_structured_evidence():
    mock_client = MagicMock()
    mock_client.search = MagicMock(return_value={"results": [
        {"content": "结果1", "title": "标题1", "url": "https://example.com/1"},
        {"content": "结果2", "title": "标题2", "url": "https://example.com/2"},
    ]})
    with patch("app.graph.tools.TavilyClient", return_value=mock_client):
        result = await tavily_search("test query", max_results=5)
    assert [item["content"] for item in result] == ["结果1", "结果2"]
    assert result[0]["source_type"] == "web"
    assert result[0]["title"] == "标题1"
    assert result[0]["url"] == "https://example.com/1"

@pytest.mark.asyncio
async def test_tavily_search_handles_empty_results():
    mock_client = MagicMock()
    mock_client.search = MagicMock(return_value={"results": []})
    with patch("app.graph.tools.TavilyClient", return_value=mock_client):
        result = await tavily_search("test")
    # 空结果时返回结构化错误条目，让 generate_answer 显示有限信息提示。
    assert result[0]["is_error"] is True
    assert "未返回结果" in result[0]["content"]


@pytest.mark.asyncio
async def test_tavily_search_handles_api_failure():
    """Tavily API 失败时不抛异常，返回错误提示字符串让流程继续。"""
    mock_client = MagicMock()
    mock_client.search = MagicMock(side_effect=Exception("API key invalid"))
    with patch("app.graph.tools.TavilyClient", return_value=mock_client):
        result = await tavily_search("test")
    # 不抛异常，返回结构化错误提示
    assert result[0]["is_error"] is True
    assert "联网搜索失败" in result[0]["content"]
    assert "Exception" in result[0]["content"]
    assert result[0]["is_error"] is True


# P1-9: Token 估算与 history 截断测试

def test_estimate_tokens_empty_string():
    assert _estimate_tokens("") == 0

def test_estimate_tokens_chinese():
    # 中文 1 字符 ≈ 1 token，估算偏保守
    assert _estimate_tokens("你好世界") >= 1

def test_estimate_tokens_english():
    # 英文 4 字符 ≈ 1 token，估算偏保守
    assert _estimate_tokens("hello world") >= 1

def test_truncate_history_empty():
    assert _truncate_history([]) == []

def test_truncate_history_keeps_all_when_under_budget():
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮您？"},
    ]
    result = _truncate_history(history, max_tokens=1000)
    assert len(result) == 2
    # 顺序保持不变
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"

def test_truncate_history_drops_oldest_when_over_budget():
    """超出预算时从最旧的消息开始丢弃。"""
    # P1-11: tiktoken 对重复字符计数更少（"x"*50 ≈ 7 tokens）
    # 用中文确保每条消息 token 数足够触发截断
    history = [
        {"role": "user", "content": "你好世界" * 20},  # ~100 tokens
        {"role": "assistant", "content": "你好世界" * 20},
        {"role": "user", "content": "你好世界" * 20},
        {"role": "assistant", "content": "你好世界" * 20},
    ]
    # 预算 150 tokens，每条 ~100 tokens，最多容纳 1 条（最新）
    result = _truncate_history(history, max_tokens=150)
    assert len(result) <= 2
    # 保留最新的消息
    assert result[-1]["content"] == "你好世界" * 20

def test_truncate_history_always_keeps_latest_even_if_overlong():
    """单条消息超长时也保留最新一条，避免完全丢失上下文。"""
    history = [
        {"role": "user", "content": "x" * 1000},
    ]
    # 预算 10 tokens，远小于单条消息
    result = _truncate_history(history, max_tokens=10)
    assert len(result) == 1
    assert result[0]["content"] == "x" * 1000
