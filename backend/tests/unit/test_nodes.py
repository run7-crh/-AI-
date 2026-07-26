# backend/tests/unit/test_nodes.py
import pytest
from unittest.mock import patch, AsyncMock
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
