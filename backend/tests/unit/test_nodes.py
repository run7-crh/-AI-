# backend/tests/unit/test_nodes.py
"""节点单元测试（对齐当前工作流：decompose + multi_step + combined_quality_check）。

节点列表：
- rewrite_query_node：不传 history，容错退回原始 query
- decompose_question_node：意图分类（chitchat/decomposition/normal）
- judge_relevance_node：轻量检索+阈值短路，低分走 LLM（修复 🔴 误判）
- rag_retrieve_node：检索 + 计算 avg_reranker_score
- rag_quality_eval_node：reranker 分数短路（高/低）+ LLM 灰色地带
- web_search_node：Tavily 联网搜索
- generate_local_node：local + chitchat 双路径
- generate_online_node：online 路径
- multi_step_reason_node：多步推理（decomposition 路径）
- combined_quality_check_node：合并幻觉+质量评估（一次 LLM 调用）
- quality_fail_node：质量警告（不覆盖 final_answer）
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.graph.state import AgentState
from app.graph.nodes import (
    rewrite_query_node,
    decompose_question_node,
    judge_relevance_node,
    rag_retrieve_node,
    rag_quality_eval_node,
    query_corrector_node,
    web_search_node,
    chitchat_node,
    generate_local_node,
    generate_online_node,
    multi_step_reason_node,
    combined_quality_check_node,
    quality_fail_node,
    RELEVANCE_SCORE_THRESHOLD,
    RELEVANCE_AVG_SCORE_THRESHOLD,
)
from app.config import settings


# ============================================================================
# rewrite_query_node
# ============================================================================
@pytest.mark.asyncio
async def test_rewrite_query_node_writes_rewritten_query():
    state = AgentState(
        query="什么是 RAG？", conversation_id="c1", history=[], judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "RAG 检索增强生成的定义", "structured": None}
        result = await rewrite_query_node(state)
    assert result["rewritten_query"] == "RAG 检索增强生成的定义"
    assert mock_llm.call_args.kwargs["temperature"] == 0.7
    assert mock_llm.call_args.kwargs["model"] == settings.MODEL_FLASH


@pytest.mark.asyncio
async def test_rewrite_query_node_fallback_on_multiline_output():
    """多行输出（疑似生成答案）时退回原始 query。"""
    state = AgentState(
        query="什么是 RAG？", conversation_id="c1", history=[], judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "RAG 是检索增强生成\n\n它通过检索外部知识来辅助生成", "structured": None}
        result = await rewrite_query_node(state)
    assert result["rewritten_query"] == "什么是 RAG？"


@pytest.mark.asyncio
async def test_rewrite_query_node_fallback_on_too_long_output():
    """输出超长（>200 字符）时退回原始 query。"""
    state = AgentState(
        query="短问题", conversation_id="c1", history=[], judge_log=[],
    )
    long_output = "这是一段超长的回答" * 50
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": long_output, "structured": None}
        result = await rewrite_query_node(state)
    assert result["rewritten_query"] == "短问题"


@pytest.mark.asyncio
async def test_rewrite_query_node_fallback_on_markdown_header():
    """输出以 # 开头（Markdown 标题）时退回原始 query。"""
    state = AgentState(
        query="标题测试", conversation_id="c1", history=[], judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "# RAG 的定义", "structured": None}
        result = await rewrite_query_node(state)
    assert result["rewritten_query"] == "标题测试"


# ============================================================================
# decompose_question_node
# ============================================================================
@pytest.mark.asyncio
async def test_decompose_question_node_normal_question():
    """普通问题：is_chitchat=false, needs_decomposition=false。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="什么是 Agent", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"is_chitchat": False, "needs_decomposition": False, "reasoning_steps": []},
        }
        result = await decompose_question_node(state)
    assert result["is_chitchat"] is False
    assert result["needs_decomposition"] is False
    assert result["reasoning_steps"] == []
    # 验证温度 0.3
    assert mock_llm.call_args.kwargs["temperature"] == 0.3
    # 验证用 DecomposeSchema
    assert mock_llm.call_args.kwargs["output_schema"] is not None


@pytest.mark.asyncio
async def test_decompose_question_node_chitchat():
    """闲聊类：is_chitchat=true, needs_decomposition=false。"""
    state = AgentState(
        query="你好", conversation_id="c1", history=[],
        rewritten_query="你好", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"is_chitchat": True, "needs_decomposition": False, "reasoning_steps": []},
        }
        result = await decompose_question_node(state)
    assert result["is_chitchat"] is True
    assert result["needs_decomposition"] is False


@pytest.mark.asyncio
async def test_decompose_question_node_needs_decomposition():
    """对比类问题：needs_decomposition=true, reasoning_steps 非空。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="LangChain, LangGraph 和 LlamaIndex 的区别",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {
                "is_chitchat": False, "needs_decomposition": True,
                "reasoning_steps": [{"sub_query": "LangChain 是什么"}, {"sub_query": "LangGraph 是什么"}],
            },
        }
        result = await decompose_question_node(state)
    assert result["needs_decomposition"] is True
    assert len(result["reasoning_steps"]) == 2


@pytest.mark.asyncio
async def test_decompose_question_node_multi_concept_relation():
    """多概念关联类：needs_decomposition=false（防 L48 误触，路由稳定性修复）。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="RAG和模型微调和幻觉有什么关联", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"is_chitchat": False, "needs_decomposition": False, "reasoning_steps": []},
        }
        result = await decompose_question_node(state)
    assert result["needs_decomposition"] is False
    assert result["reasoning_steps"] == []


@pytest.mark.asyncio
async def test_decompose_question_node_explicit_respective():
    """显式"分别"并列子问题：needs_decomposition=true。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="RAG、模型微调、幻觉分别是什么", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {
                "is_chitchat": False, "needs_decomposition": True,
                "reasoning_steps": [
                    {"sub_query": "RAG 是什么"},
                    {"sub_query": "模型微调是什么"},
                    {"sub_query": "幻觉是什么"},
                ],
            },
        }
        result = await decompose_question_node(state)
    assert result["needs_decomposition"] is True
    assert len(result["reasoning_steps"]) == 3


@pytest.mark.asyncio
async def test_decompose_question_node_handles_malformed_structured_output():
    """结构化输出缺字段时应安全降级到普通问题，而不是让 SSE 直接失败。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": {"is_chitchat": "maybe"}}
        result = await decompose_question_node(state)
    assert result == {
        "is_chitchat": False,
        "needs_decomposition": False,
        "reasoning_steps": [],
    }


@pytest.mark.asyncio
async def test_decompose_question_node_handles_structured_call_failure():
    """模型结构化调用抛错时也应回退到普通相关性判断。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = ValueError("invalid structured output")
        result = await decompose_question_node(state)
    assert result == {
        "is_chitchat": False,
        "needs_decomposition": False,
        "reasoning_steps": [],
    }


# ============================================================================
# judge_relevance_node（轻量检索+阈值短路，修复 🔴 误判）
# ============================================================================
@pytest.mark.asyncio
async def test_judge_relevance_high_score_short_circuits_to_true():
    """🔴 回归测试：高分短路判 relevant=true，跳过 LLM。

    这是修复"什么是RAG"误判的核心：检索器命中知识库且高分 → 直接判相关。
    """
    mock_retriever = MagicMock()
    state = AgentState(
        query="什么是RAG", conversation_id="c1", history=[],
        rewritten_query="什么是 RAG 检索增强生成", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_ret.return_value = [
            {"content": "RAG 是检索增强生成...", "source": "RAG 检索增强生成.md", "title": "RAG", "score": 0.85}
        ]
        result = await judge_relevance_node(state, mock_retriever)

    assert result["is_relevant"] is True
    # 关键：LLM 未被调用（短路）
    mock_eval.assert_not_called()
    # 验证 judge_log 记录了短路方法
    assert result["judge_log"][0]["raw_output"]["method"] == "light_retrieval"
    assert result["judge_log"][0]["raw_output"]["top_score"] == 0.85


@pytest.mark.asyncio
async def test_judge_relevance_low_score_falls_back_to_llm():
    """低分（< 阈值）时降级到 LLM 判断。"""
    mock_retriever = MagicMock()
    state = AgentState(
        query="介绍一下江门", conversation_id="c1", history=[],
        rewritten_query="介绍一下江门", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_ret.return_value = [
            {"content": "无关内容", "source": "other.md", "title": "X", "score": 0.2}
        ]
        mock_eval.return_value = {"judge_type": "is_relevant", "passed": False, "raw_output": {}}
        result = await judge_relevance_node(state, mock_retriever)

    assert result["is_relevant"] is False
    # LLM 被调用
    mock_eval.assert_called_once()
    # 验证用原始 query 给 LLM（不是 rewritten_query）
    assert mock_eval.call_args.kwargs["query"] == "介绍一下江门"


@pytest.mark.asyncio
async def test_judge_relevance_empty_retrieval_falls_back_to_llm():
    """检索无结果时降级到 LLM 判断。"""
    mock_retriever = MagicMock()
    state = AgentState(
        query="冷门问题", conversation_id="c1", history=[],
        rewritten_query="冷门问题", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_ret.return_value = []
        mock_eval.return_value = {"judge_type": "is_relevant", "passed": False, "raw_output": {}}
        result = await judge_relevance_node(state, mock_retriever)

    assert result["is_relevant"] is False
    mock_eval.assert_called_once()


@pytest.mark.asyncio
async def test_judge_relevance_retrieval_error_falls_back_to_llm():
    """轻量检索异常时不阻塞，降级到 LLM 判断。"""
    mock_retriever = MagicMock()
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="x", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_ret.side_effect = RuntimeError("检索器异常")
        mock_eval.return_value = {"judge_type": "is_relevant", "passed": True, "raw_output": {}}
        result = await judge_relevance_node(state, mock_retriever)

    assert result["is_relevant"] is True
    mock_eval.assert_called_once()


@pytest.mark.asyncio
async def test_judge_relevance_threshold_boundary():
    """阈值边界：score 恰好等于阈值时短路通过（>= 判断）。"""
    mock_retriever = MagicMock()
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="x", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_ret.return_value = [
            {"content": "内容", "source": "a.md", "title": "A", "score": RELEVANCE_SCORE_THRESHOLD}
        ]
        result = await judge_relevance_node(state, mock_retriever)

    assert result["is_relevant"] is True
    mock_eval.assert_not_called()


@pytest.mark.asyncio
async def test_judge_relevance_uses_rewritten_query_for_retrieval():
    """验证轻量检索用 rewritten_query（更适合检索）。

    P1-4: 现在retrieve 被调用两次（top_k=1 轻量 + top_k=3 完整），
    两次都用 rewritten_query。验证最后一次调用的参数。
    """
    mock_retriever = MagicMock()
    state = AgentState(
        query="原始", conversation_id="c1", history=[],
        rewritten_query="改写后的完整问题", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_ret.return_value = []
        mock_eval.return_value = {
            "passed": False,
            "judge_type": "is_relevant",
            "raw_output": {"reason": "test"},
        }
        await judge_relevance_node(state, mock_retriever)
    # P1-4: retrieve 被调用两次（轻量 top_k=1 + 完整 top_k=3）
    assert mock_ret.call_count == 2
    # 两次都用 rewritten_query
    assert mock_ret.call_args.args[0] == "改写后的完整问题"
    # 第一次轻量检索 top_k=1
    assert mock_ret.call_args_list[0].kwargs["top_k"] == 1
    # P1-4: 第二次完整检索 top_k=3
    assert mock_ret.call_args_list[1].kwargs["top_k"] == 3


# ============================================================================
# rag_retrieve_node
# ============================================================================
@pytest.mark.asyncio
async def test_rag_retrieve_node_writes_retrieval_result_and_avg_score():
    """验证 rag_retrieve 写 retrieval_result 和 avg_reranker_score。"""
    mock_retriever = MagicMock()
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="Agent 是什么", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret:
        mock_ret.return_value = [
            {"content": "c1", "source": "a.md", "title": "A", "score": 0.9},
            {"content": "c2", "source": "b.md", "title": "B", "score": 0.5},
        ]
        result = await rag_retrieve_node(state, mock_retriever)

    assert len(result["retrieval_result"]) == 2
    # avg_score = (0.9 + 0.5) / 2 = 0.7
    assert result["avg_reranker_score"] == 0.7


@pytest.mark.asyncio
async def test_rag_retrieve_node_empty_result_avg_score_zero():
    """空检索结果时 avg_score=0。"""
    mock_retriever = MagicMock()
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="无结果", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret:
        mock_ret.return_value = []
        result = await rag_retrieve_node(state, mock_retriever)
    assert result["retrieval_result"] == []
    assert result["avg_reranker_score"] == 0.0


# ============================================================================
# rag_quality_eval_node（reranker 分数短路）
# ============================================================================
@pytest.mark.asyncio
async def test_rag_quality_eval_high_score_short_circuits_pass():
    """高分（>0.7）短路通过，跳过 LLM。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="Agent",
        retrieval_result=[{"content": "Agent 是...", "source": "a.md", "title": "A", "score": 0.9}],
        avg_reranker_score=0.9,
        judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        result = await rag_quality_eval_node(state)

    assert result["rag_quality_pass"] is True
    mock_eval.assert_not_called()
    assert result["judge_log"][0]["raw_output"]["short_circuit"] == "high"


@pytest.mark.asyncio
async def test_rag_quality_eval_low_score_short_circuits_fail():
    """低分（<0.3）短路不通过，跳过 LLM。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="无关",
        retrieval_result=[{"content": "无关内容", "source": "a.md", "title": "A", "score": 0.1}],
        avg_reranker_score=0.1,
        judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        result = await rag_quality_eval_node(state)

    assert result["rag_quality_pass"] is False
    mock_eval.assert_not_called()
    assert result["judge_log"][0]["raw_output"]["short_circuit"] == "low"


@pytest.mark.asyncio
async def test_rag_quality_eval_gray_zone_uses_llm():
    """灰色地带（0.3~0.7）调 LLM 精细判断。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="模糊问题",
        retrieval_result=[{"content": "部分相关", "source": "a.md", "title": "A", "score": 0.5}],
        avg_reranker_score=0.5,
        judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = {"judge_type": "is_retrieval_quality", "passed": True, "raw_output": {}}
        result = await rag_quality_eval_node(state)

    assert result["rag_quality_pass"] is True
    mock_eval.assert_called_once()


@pytest.mark.asyncio
async def test_rag_quality_eval_empty_result_fails():
    """空检索结果直接不通过。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="x",
        retrieval_result=[],
        avg_reranker_score=0.0,
        judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        result = await rag_quality_eval_node(state)
    assert result["rag_quality_pass"] is False
    mock_eval.assert_not_called()


# ============================================================================
# web_search_node
# ============================================================================
@pytest.mark.asyncio
async def test_web_search_node_writes_web_search_result():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="最新新闻", judge_log=[],
    )
    with patch("app.graph.nodes.tavily_search", new_callable=AsyncMock) as mock_ts:
        mock_ts.return_value = [{
            "source_type": "web", "title": "新闻", "url": "https://example.com",
            "source": "新闻", "content": "新闻内容",
        }]
        result = await web_search_node(state)
    assert result["web_search_result"][0]["content"] == "新闻内容"


# ============================================================================
# generate_local_node（local + chitchat 双路径）
# ============================================================================
@pytest.mark.asyncio
async def test_generate_local_node_local_path():
    """local 路径：基于 retrieval_result 生成，route_path=local。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="什么是 Agent",
        retrieval_result=[{"content": "Agent 是...", "source": "Agent.md", "title": "Agent", "score": 0.9}],
        is_chitchat=False,
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "Agent 是一种...", "structured": None}
        result = await generate_local_node(state, None)

    assert result["final_answer"] == "Agent 是一种..."
    assert result["route_path"] == "local"
    assert mock_llm.call_args.kwargs["stream"] is True
    assert mock_llm.call_args.kwargs["model"] == settings.MODEL_PRO_CHAT
    # system_prompt 含检索内容
    assert "Agent 是..." in mock_llm.call_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_chitchat_node_returns_chitchat_response():
    """P1-6: chitchat_node 用 CHITCHAT_PROMPT，route_path=chitchat。"""
    state = AgentState(
        query="你好", conversation_id="c1", history=[],
        rewritten_query="你好",
        is_chitchat=True,
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "你好，很高兴见到你！", "structured": None}
        result = await chitchat_node(state, None)

    assert result["final_answer"] == "你好，很高兴见到你！"
    assert result["route_path"] == "chitchat"


@pytest.mark.asyncio
async def test_chitchat_node_fallback_on_error():
    """P1-6: chitchat_node LLM 失败时降级提示。"""
    state = AgentState(
        query="你好", conversation_id="c1", history=[],
        rewritten_query="你好",
        is_chitchat=True,
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("LLM 调用失败")
        result = await chitchat_node(state, None)

    assert result["route_path"] == "chitchat"
    assert "你好" in result["final_answer"]  # 降级兜底文本


@pytest.mark.asyncio
async def test_generate_local_node_local_fallback_on_error():
    """local 路径 LLM 失败时降级提示。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试",
        retrieval_result=[{"content": "内容", "source": "a.md", "title": "A", "score": 0.9}],
        is_chitchat=False,
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = RuntimeError("API 超时")
        result = await generate_local_node(state, None)
    assert "抱歉" in result["final_answer"]
    assert result["route_path"] == "local"


# ============================================================================
# generate_online_node
# ============================================================================
@pytest.mark.asyncio
async def test_generate_online_node_writes_final_answer():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="最新新闻",
        web_search_result="[1] 新闻内容",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "根据最新搜索...", "structured": None}
        result = await generate_online_node(state, None)

    assert result["final_answer"] == "根据最新搜索..."
    assert result["route_path"] == "online"
    assert mock_llm.call_args.kwargs["stream"] is True


@pytest.mark.asyncio
async def test_generate_online_node_fallback_on_error():
    """LLM 失败时降级提示。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试",
        web_search_result="搜索结果",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = RuntimeError("API 超时")
        result = await generate_online_node(state, None)
    assert "抱歉" in result["final_answer"]
    assert result["route_path"] == "online"


# ============================================================================
# multi_step_reason_node
# ============================================================================
@pytest.mark.asyncio
async def test_multi_step_reason_node_writes_final_answer_and_route():
    """多步推理：写 final_answer，route_path=decomposition，用 reasoner 模型。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="对比 A 和 B",
        needs_decomposition=True,
        reasoning_steps=[{"sub_query": "A 是什么"}, {"sub_query": "B 是什么"}],
        judge_log=[],
    )
    mock_retriever = MagicMock()
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_ret.return_value = [{"content": "检索内容", "source": "a.md", "title": "A", "score": 0.9}]
        mock_llm.return_value = {"text": "## 推理过程\n...\n## 结论\n最终答案", "structured": None}
        result = await multi_step_reason_node(state, None, rag_retriever=mock_retriever)

    assert result["final_answer"] == "## 推理过程\n...\n## 结论\n最终答案"
    assert result["route_path"] == "decomposition"
    # 验证用 MODEL_PRO_REASON
    assert mock_llm.call_args.kwargs["model"] == settings.MODEL_PRO_REASON
    # 验证温度 0.5
    assert mock_llm.call_args.kwargs["temperature"] == 0.5
    # 验证流式
    assert mock_llm.call_args.kwargs["stream"] is True
    # 验证对每个子问题调用了 retrieve
    assert mock_ret.call_count == 2


@pytest.mark.asyncio
async def test_multi_step_reason_node_fallback_on_error():
    """LLM 失败时降级提示。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试",
        needs_decomposition=True,
        reasoning_steps=[{"sub_query": "子问题"}],
        judge_log=[],
    )
    mock_retriever = MagicMock()
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_ret.return_value = []
        mock_llm.side_effect = RuntimeError("API 超时")
        result = await multi_step_reason_node(state, None, rag_retriever=mock_retriever)
    assert "抱歉" in result["final_answer"]
    assert result["route_path"] == "decomposition"


@pytest.mark.asyncio
async def test_multi_step_reason_node_fills_missing_subquery_from_web():
    """多步问题中本地无命中的子问题应补充 Web 证据。"""
    state = AgentState(
        query="对比本地主题和最新资料", conversation_id="c1", history=[],
        rewritten_query="对比本地主题和最新资料",
        needs_decomposition=True,
        reasoning_steps=[{"sub_query": "本地主题"}, {"sub_query": "最新资料"}],
        judge_log=[],
    )
    mock_retriever = MagicMock()
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.tavily_search", new_callable=AsyncMock) as mock_search, \
         patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        # 第一个子问题命中本地，第二个需要联网补充。
        mock_ret.side_effect = [
            [{"content": "本地内容", "source": "local.md", "title": "Local", "score": 0.8}],
            [],
        ]
        mock_search.return_value = [{
            "source_type": "web", "source": "web", "title": "官方资料",
            "url": "https://example.com", "content": "最新内容", "score": None,
        }]
        mock_llm.return_value = {"text": "综合答案", "structured": None}
        result = await multi_step_reason_node(state, None, rag_retriever=mock_retriever)

    mock_search.assert_awaited_once_with("最新资料")
    assert result["route_path"] == "decomposition"
    assert any(r.get("source") == "local.md" for r in result["retrieval_result"])
    assert any(r.get("source_type") == "web" for r in result["retrieval_result"])
    assert result["web_search_result"][0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_multi_step_reason_node_does_not_search_when_all_subqueries_hit():
    """所有子问题都有本地证据时，不产生不必要的外部调用。"""
    state = AgentState(
        query="对比 A 和 B", conversation_id="c1", history=[],
        rewritten_query="对比 A 和 B", needs_decomposition=True,
        reasoning_steps=[{"sub_query": "A"}, {"sub_query": "B"}], judge_log=[],
    )
    mock_retriever = MagicMock()
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.tavily_search", new_callable=AsyncMock) as mock_search, \
         patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_ret.return_value = [{"content": "命中", "source": "a.md", "title": "A", "score": 0.8}]
        mock_llm.return_value = {"text": "答案", "structured": None}
        await multi_step_reason_node(state, None, rag_retriever=mock_retriever)

    mock_search.assert_not_awaited()


# ============================================================================
# combined_quality_check_node（P1-1 合并幻觉+质量）
# ============================================================================
@pytest.mark.asyncio
async def test_combined_quality_check_local_path_pass():
    """local 路径：无幻觉+质量通过 → passed=true。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="什么是 Agent",
        route_path="local",
        retrieval_result=[{"content": "Agent 是...", "source": "a.md", "title": "A", "score": 0.9}],
        final_answer="Agent 是...",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"has_hallucination": False, "answer_quality_pass": True, "reason": "ok"},
        }
        result = await combined_quality_check_node(state)

    assert result["has_hallucination"] is False
    assert result["answer_quality_pass"] is True
    # judge_log 的 passed = not hallucination and quality_pass
    assert result["judge_log"][0]["passed"] is True
    assert result["judge_log"][0]["judge_type"] == "combined_quality"


@pytest.mark.asyncio
async def test_combined_quality_check_online_path_uses_web_search_result():
    """online 路径：source 取自 web_search_result。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="最新新闻",
        route_path="online",
        web_search_result="搜索结果内容",
        final_answer="根据搜索...",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"has_hallucination": False, "answer_quality_pass": True, "reason": "ok"},
        }
        result = await combined_quality_check_node(state)

    # 验证 system_prompt 含 web_search_result
    system_prompt = mock_llm.call_args.kwargs["system_prompt"]
    assert "搜索结果内容" in system_prompt


@pytest.mark.asyncio
async def test_combined_quality_check_has_hallucination_fails():
    """有幻觉 → passed=false。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试",
        route_path="local",
        retrieval_result=[{"content": "真实内容", "source": "a.md", "title": "A", "score": 0.9}],
        final_answer="编造的答案",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"has_hallucination": True, "answer_quality_pass": True, "reason": "幻觉"},
        }
        result = await combined_quality_check_node(state)

    assert result["has_hallucination"] is True
    assert result["judge_log"][0]["passed"] is False


@pytest.mark.asyncio
async def test_combined_quality_check_fallback_on_error():
    """评估器失败时保持幻觉未知，不把基础设施错误当成幻觉。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试",
        route_path="local",
        retrieval_result=[{"content": "内容", "source": "a.md", "title": "A", "score": 0.9}],
        final_answer="答案",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("LLM 调用失败")
        result = await combined_quality_check_node(state)

    assert result["has_hallucination"] is None
    assert result["answer_quality_pass"] is False
    assert result["quality_check_error"] == "Exception"
    assert result["judge_log"][0]["passed"] is False


# ============================================================================
# quality_fail_node（P1-3: 不覆盖 final_answer，写 quality_warning）
# ============================================================================
@pytest.mark.asyncio
async def test_quality_fail_node_hallucination_warning():
    """有幻觉时写幻觉警告，不覆盖 final_answer。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试",
        route_path="local",
        final_answer="原始答案",
        has_hallucination=True,
        answer_quality_pass=True,
        judge_log=[],
    )
    result = await quality_fail_node(state)
    # 不覆盖 final_answer
    assert "final_answer" not in result
    assert "quality_warning" in result
    assert "未经验证" in result["quality_warning"]


@pytest.mark.asyncio
async def test_quality_fail_node_quality_warning():
    """质量不通过时写质量警告。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试",
        route_path="online",
        final_answer="原始答案",
        has_hallucination=False,
        answer_quality_pass=False,
        judge_log=[],
    )
    result = await quality_fail_node(state)
    assert "final_answer" not in result
    assert "质量评估未通过" in result["quality_warning"]


@pytest.mark.asyncio
async def test_quality_fail_node_reports_checker_error_separately():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="测试", route_path="local", final_answer="原始答案",
        has_hallucination=None, answer_quality_pass=False,
        quality_check_error="TimeoutError", judge_log=[],
    )
    result = await quality_fail_node(state)
    assert "检查暂时不可用" in result["quality_warning"]


# ============================================================================
# query_corrector_node（CRAG: 检索失败后的二次改写）
# ============================================================================
@pytest.mark.asyncio
async def test_query_corrector_node_rewrites_query_and_increments_count():
    """CRAG: 正常改写查询 + 递增 correction_count。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="RAG 检索增强生成",
        judge_log=[{
            "judge_type": "is_retrieval_quality",
            "passed": False,
            "raw_output": {"reason": "low reranker score", "short_circuit": "low", "avg_score": 0.2},
        }],
        correction_count=0,
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "RAG 检索增强", "structured": None}
        result = await query_corrector_node(state)

    assert result["rewritten_query"] == "RAG 检索增强"
    assert result["correction_count"] == 1
    # 验证 prompt 含失败原因
    system_prompt = mock_llm.call_args.kwargs["system_prompt"]
    assert "low reranker score" in system_prompt
    # 验证用 MODEL_FLASH
    assert mock_llm.call_args.kwargs["model"] == settings.MODEL_FLASH


@pytest.mark.asyncio
async def test_query_corrector_node_fallback_on_abnormal_output():
    """CRAG: LLM 输出异常（多行/超长）时保留原查询，仍递增计数。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="原始查询",
        judge_log=[{
            "judge_type": "is_retrieval_quality",
            "passed": False,
            "raw_output": {"reason": "empty retrieval"},
        }],
        correction_count=0,
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "这是答案\n\n不是改写", "structured": None}
        result = await query_corrector_node(state)

    # 保留原查询
    assert result["rewritten_query"] == "原始查询"
    # 计数仍递增（表示已尝试纠正一次）
    assert result["correction_count"] == 1


@pytest.mark.asyncio
async def test_query_corrector_node_fallback_on_llm_error():
    """CRAG: LLM 调用失败时保留原查询，仍递增计数（防死循环）。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="原始查询",
        judge_log=[{
            "judge_type": "is_retrieval_quality",
            "passed": False,
            "raw_output": {"reason": "low reranker score"},
        }],
        correction_count=0,
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("LLM 调用失败")
        result = await query_corrector_node(state)

    assert result["rewritten_query"] == "原始查询"
    assert result["correction_count"] == 1
