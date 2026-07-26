# backend/tests/unit/test_nodes.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.graph.state import AgentState
from app.graph.nodes import rewrite_query_node, decompose_question_node
from app.config import settings

@pytest.mark.asyncio
async def test_rewrite_query_node_writes_rewritten_query():
    state = AgentState(
        query="什么是 RAG？", conversation_id="c1", history=[], judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "RAG 检索增强生成的定义", "structured": None}
        result = await rewrite_query_node(state)
    assert result["rewritten_query"] == "RAG 检索增强生成的定义"
    mock_llm.assert_called_once()
    # 验证温度 0.7
    assert mock_llm.call_args.kwargs["temperature"] == 0.7

@pytest.mark.asyncio
async def test_decompose_question_node_returns_needs_decomposition():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="复杂问题", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"needs_decomposition": True, "reasoning_steps": [{"sub_query": "子问题1"}]},
        }
        result = await decompose_question_node(state)
    assert result["needs_decomposition"] is True
    assert len(result["reasoning_steps"]) == 1
    # 验证温度 0.3
    assert mock_llm.call_args.kwargs["temperature"] == 0.3

@pytest.mark.asyncio
async def test_decompose_question_node_no_decomposition():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="简单问题", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"needs_decomposition": False, "reasoning_steps": []},
        }
        result = await decompose_question_node(state)
    assert result["needs_decomposition"] is False
    assert result["reasoning_steps"] == []

from app.graph.nodes import multi_step_reason_node

@pytest.mark.asyncio
async def test_multi_step_reason_node_writes_final_answer():
    """验证修复点 1：多步推理节点直接写 final_answer。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="复杂推理问题",
        needs_decomposition=True,
        reasoning_steps=[{"sub_query": "子问题1"}, {"sub_query": "子问题2"}],
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "## 推理过程\n...\n## 结论\n最终答案", "structured": None}
        result = await multi_step_reason_node(state)
    # 关键断言：final_answer 被写入
    assert result["final_answer"] == "## 推理过程\n...\n## 结论\n最终答案"
    # route_path 标记为 decomposition
    assert result["route_path"] == "decomposition"
    # 验证使用 deepseek-reasoner 模型
    assert mock_llm.call_args.kwargs["model"] == settings.MODEL_PRO_REASON
    # 验证温度 0.5
    assert mock_llm.call_args.kwargs["temperature"] == 0.5

from app.graph.nodes import judge_relevance_node, rag_retrieve_node, web_search_node

@pytest.mark.asyncio
async def test_judge_relevance_node_writes_is_relevant():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="什么是 Agent", judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = {"judge_type": "is_relevant", "passed": True, "raw_output": {}}
        result = await judge_relevance_node(state)
    assert result["is_relevant"] is True
    assert len(result["judge_log"]) == 1

@pytest.mark.asyncio
async def test_rag_retrieve_node_does_retrieve_and_quality_eval():
    """验证 rag_retrieve 节点同时做检索和 RAG 质量评估。"""
    mock_retriever = MagicMock()
    mock_retriever.retrieve = MagicMock(return_value=[
        {"content": "c1", "source": "a.md", "title": "A", "score": 0.9}
    ])
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="Agent 是什么", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_ret.return_value = [{"content": "c1", "source": "a.md", "title": "A", "score": 0.9}]
        mock_eval.return_value = {"judge_type": "is_quality_pass", "passed": True, "raw_output": {}}
        result = await rag_retrieve_node(state, mock_retriever)

    # 验证检索被调用
    mock_ret.assert_called_once()
    # 验证 RAG 质量评估被调用
    mock_eval.assert_called_once()
    assert mock_eval.call_args.kwargs["judge_type"] == "is_quality_pass"
    # 验证 state 字段
    assert result["retrieval_result"][0]["content"] == "c1"
    assert result["rag_quality_pass"] is True

@pytest.mark.asyncio
async def test_web_search_node_writes_web_search_result():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="最新新闻", judge_log=[],
    )
    with patch("app.graph.nodes.tavily_search", new_callable=AsyncMock) as mock_ts:
        mock_ts.return_value = "[1] 新闻内容"
        result = await web_search_node(state)
    assert result["web_search_result"] == "[1] 新闻内容"
