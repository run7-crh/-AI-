# backend/tests/unit/test_builder.py
"""图结构与路由测试（对齐当前工作流：decompose + chitchat_node + multi_step + combined_quality_check + CRAG 回路）。

工作流拓扑（P1-6: chitchat 拆分为独立节点，CRAG: 检索失败纠正一次）：
  rewrite_query → decompose_question
    ├─ is_chitchat=true → chitchat_node → END（跳过质量检查）
    ├─ needs_decomposition=true → multi_step_reason → combined_quality_check
    │                                                ├─ pass → END
    │                                                └─ fail → quality_fail → END
    └─ else → judge_relevance
                ├─ relevant → rag_retrieve → rag_quality_eval
                │               ├─ pass → generate_local → combined_quality_check → ...
                │               └─ fail → query_corrector → rag_retrieve → rag_quality_eval
                │                          (correction_count < 1)      ├─ pass → generate_local → ...
                │                                                        └─ fail → web_search → generate_online → ...
                └─ not relevant → web_search → generate_online → combined_quality_check → ...
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.graph.builder import (
    build_graph,
    route_after_decompose,
    route_after_relevance,
    route_after_rag_quality,
    route_after_generate,
    route_after_combined_quality,
)
from langgraph.graph import END


# ============================================================================
# route_after_decompose：意图分类后路由
# ============================================================================
def test_route_after_decompose_chitchat_goes_chitchat_node():
    """P1-6: 闲聊 → chitchat_node（独立节点，不再走 generate_local）。"""
    state = {"is_chitchat": True, "needs_decomposition": False}
    assert route_after_decompose(state) == "chitchat_node"


def test_route_after_decompose_decomposition_goes_multi_step():
    """需要分解 → multi_step_reason。"""
    state = {"is_chitchat": False, "needs_decomposition": True}
    assert route_after_decompose(state) == "multi_step_reason"


def test_route_after_decompose_normal_goes_judge_relevance():
    """普通问题 → judge_relevance。"""
    state = {"is_chitchat": False, "needs_decomposition": False}
    assert route_after_decompose(state) == "judge_relevance"


def test_route_after_decompose_chitchat_overrides_decomposition():
    """chitchat 优先级高于 decomposition。"""
    state = {"is_chitchat": True, "needs_decomposition": True}
    assert route_after_decompose(state) == "chitchat_node"


def test_route_after_decompose_missing_keys_defaults_to_judge_relevance():
    """缺失字段时默认走 judge_relevance。"""
    state = {}
    assert route_after_decompose(state) == "judge_relevance"


# ============================================================================
# route_after_relevance：相关性判断后路由
# ============================================================================
def test_route_after_relevance_true():
    state = {"is_relevant": True}
    assert route_after_relevance(state) == "rag_retrieve"


def test_route_after_relevance_false():
    state = {"is_relevant": False}
    assert route_after_relevance(state) == "web_search"


# ============================================================================
# route_after_rag_quality：RAG 质量评估后路由（CRAG 回路）
# ============================================================================
def test_route_after_rag_quality_pass_goes_generate_local():
    state = {"rag_quality_pass": True}
    assert route_after_rag_quality(state) == "generate_local"


def test_route_after_rag_quality_fail_first_time_goes_query_corrector():
    """CRAG: 首次失败（correction_count=0）→ query_corrector 重试。"""
    state = {"rag_quality_pass": False, "correction_count": 0}
    assert route_after_rag_quality(state) == "query_corrector"


def test_route_after_rag_quality_fail_second_time_goes_web_search():
    """CRAG: 第二次失败（correction_count>=1）→ web_search 放弃检索。"""
    state = {"rag_quality_pass": False, "correction_count": 1}
    assert route_after_rag_quality(state) == "web_search"


def test_route_after_rag_quality_fail_no_count_field_defaults_to_corrector():
    """correction_count 字段缺失时默认走 query_corrector（get 默认 0）。"""
    state = {"rag_quality_pass": False}
    assert route_after_rag_quality(state) == "query_corrector"


# ============================================================================
# route_after_generate：生成后路由（P1-6: chitchat 已拆分，统一进质量评估）
# ============================================================================
def test_route_after_generate_local_goes_quality_check():
    state = {"route_path": "local"}
    assert route_after_generate(state) == "combined_quality_check"


def test_route_after_generate_online_goes_quality_check():
    state = {"route_path": "online"}
    assert route_after_generate(state) == "combined_quality_check"


def test_route_after_generate_decomposition_goes_quality_check():
    """decomposition 路径也进质量检查。"""
    state = {"route_path": "decomposition"}
    assert route_after_generate(state) == "combined_quality_check"


# ============================================================================
# route_after_combined_quality：合并质量评估后路由
# ============================================================================
def test_route_after_combined_quality_pass_ends():
    """无幻觉+质量通过 → END。"""
    state = {"has_hallucination": False, "answer_quality_pass": True}
    assert route_after_combined_quality(state) == END


def test_route_after_combined_quality_hallucination_fails():
    """有幻觉 → quality_fail。"""
    state = {"has_hallucination": True, "answer_quality_pass": True}
    assert route_after_combined_quality(state) == "quality_fail"


def test_route_after_combined_quality_low_quality_fails():
    """质量不通过 → quality_fail。"""
    state = {"has_hallucination": False, "answer_quality_pass": False}
    assert route_after_combined_quality(state) == "quality_fail"


def test_route_after_combined_quality_both_fail():
    """双重失败 → quality_fail。"""
    state = {"has_hallucination": True, "answer_quality_pass": False}
    assert route_after_combined_quality(state) == "quality_fail"


# ============================================================================
# build_graph：图构建与端到端拓扑验证
# ============================================================================
def test_build_graph_returns_compiled():
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)
    assert hasattr(graph, "ainvoke")
    assert hasattr(graph, "astream_events")


@pytest.mark.asyncio
async def test_build_graph_local_path_end_to_end():
    """端到端验证 local 路径：rewrite → decompose(normal) → judge_relevance(短路高分)
    → rag_retrieve → rag_quality_eval(高分短路) → generate_local
    → combined_quality_check(pass) → END

    这条路径正是测试报告 🔴 修复后应触发的路径 A。
    """
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)

    initial_state = {
        "query": "什么是RAG",
        "conversation_id": "topo-local-test",
        "history": [],
        "judge_log": [],
    }

    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval, \
         patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret:
        mock_llm.side_effect = [
            {"text": "什么是 RAG 检索增强生成", "structured": None},  # rewrite_query
            {"text": "", "structured": {"is_chitchat": False, "needs_decomposition": False, "reasoning_steps": []}},  # decompose
            {"text": "RAG 是检索增强生成...", "structured": None},  # generate_local
            {"text": "", "structured": {"has_hallucination": False, "answer_quality_pass": True, "reason": "ok"}},  # combined_quality_check
        ]
        # judge_relevance: 轻量检索高分短路，不调 evaluate
        # rag_quality_eval: 高分短路，不调 evaluate
        # 所以 mock_eval 不应被调用
        # retrieve 被 judge_relevance(top_k=1) 和 rag_retrieve(top_k=3) 各调一次
        mock_ret.side_effect = [
            [{"content": "RAG 是...", "source": "RAG 检索增强生成.md", "title": "RAG", "score": 0.9}],  # judge_relevance 轻量检索
            [{"content": "RAG 是...", "source": "RAG 检索增强生成.md", "title": "RAG", "score": 0.9}],  # rag_retrieve
        ]

        final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 25})

    assert final_state.get("route_path") == "local"
    assert "RAG" in final_state.get("final_answer", "")
    # judge_relevance 和 rag_quality_eval 都短路，evaluate 未被调用
    mock_eval.assert_not_called()


@pytest.mark.asyncio
async def test_build_graph_online_path_end_to_end():
    """端到端验证 online 路径：rewrite → decompose(normal) → judge_relevance(不相关)
    → web_search → generate_online → combined_quality_check(pass) → END
    """
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)

    initial_state = {
        "query": "介绍一下江门",
        "conversation_id": "topo-online-test",
        "history": [],
        "judge_log": [],
    }

    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval, \
         patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.tavily_search", new_callable=AsyncMock) as mock_ts:
        mock_llm.side_effect = [
            {"text": "介绍一下江门", "structured": None},  # rewrite_query
            {"text": "", "structured": {"is_chitchat": False, "needs_decomposition": False, "reasoning_steps": []}},  # decompose
            {"text": "江门是...", "structured": None},  # generate_online
            {"text": "", "structured": {"has_hallucination": False, "answer_quality_pass": True, "reason": "ok"}},  # combined_quality_check
        ]
        # judge_relevance: 轻量检索无结果 → LLM 判断 false
        mock_ret.return_value = []  # 轻量检索无结果
        mock_eval.return_value = {"judge_type": "is_relevant", "passed": False, "raw_output": {}}
        mock_ts.return_value = "[1] 江门新闻"

        final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 25})

    assert final_state.get("route_path") == "online"
    assert "江门" in final_state.get("final_answer", "")


@pytest.mark.asyncio
async def test_build_graph_decomposition_path_end_to_end():
    """端到端验证 decomposition 路径：rewrite → decompose(decomposition)
    → multi_step_reason → combined_quality_check(pass) → END

    对应测试报告路径 D（第3轮"LangChain/LangGraph/LlamaIndex 的区别"）。
    """
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)

    initial_state = {
        "query": "LangChain, LangGraph 和 LlamaIndex 的区别",
        "conversation_id": "topo-decomp-test",
        "history": [],
        "judge_log": [],
    }

    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret:
        mock_llm.side_effect = [
            {"text": "LangChain LangGraph LlamaIndex 的区别", "structured": None},  # rewrite_query
            {"text": "", "structured": {  # decompose
                "is_chitchat": False, "needs_decomposition": True,
                "reasoning_steps": [{"sub_query": "LangChain 是什么"}, {"sub_query": "LangGraph 是什么"}],
            }},
            {"text": "## 对比分析\n最终答案", "structured": None},  # multi_step_reason
            {"text": "", "structured": {"has_hallucination": False, "answer_quality_pass": True, "reason": "ok"}},  # combined_quality_check
        ]
        mock_ret.return_value = [{"content": "检索内容", "source": "a.md", "title": "A", "score": 0.9}]

        final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 25})

    assert final_state.get("route_path") == "decomposition"
    assert "对比分析" in final_state.get("final_answer", "")


@pytest.mark.asyncio
async def test_build_graph_chitchat_path_skips_quality_check():
    """端到端验证 chitchat 路径跳过 combined_quality_check：
    rewrite → decompose(chitchat) → chitchat_node → END
    """
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)

    initial_state = {
        "query": "你好",
        "conversation_id": "topo-chitchat-test",
        "history": [],
        "judge_log": [],
    }

    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = [
            {"text": "你好", "structured": None},  # rewrite_query
            {"text": "", "structured": {"is_chitchat": True, "needs_decomposition": False, "reasoning_steps": []}},  # decompose
            {"text": "你好，很高兴见到你！", "structured": None},  # chitchat_node
        ]

        final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 25})

    assert final_state.get("route_path") == "chitchat"
    assert "你好" in final_state.get("final_answer", "")
    # chitchat 跳过质量检查，judge_log 应为空（无 evaluate 调用）
    assert len(final_state.get("judge_log", [])) == 0


@pytest.mark.asyncio
async def test_build_graph_hallucination_routes_to_quality_fail():
    """验证幻觉检测不通过时路由到 quality_fail，写 quality_warning。"""
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)

    initial_state = {
        "query": "幻觉测试",
        "conversation_id": "topo-halluc-test",
        "history": [],
        "judge_log": [],
    }

    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval, \
         patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret:
        mock_llm.side_effect = [
            {"text": "幻觉测试", "structured": None},  # rewrite_query
            {"text": "", "structured": {"is_chitchat": False, "needs_decomposition": False, "reasoning_steps": []}},  # decompose
            {"text": "编造的答案", "structured": None},  # generate_local
            {"text": "", "structured": {"has_hallucination": True, "answer_quality_pass": True, "reason": "幻觉"}},  # combined_quality_check
        ]
        mock_ret.side_effect = [
            [{"content": "真实内容", "source": "a.md", "title": "A", "score": 0.9}],  # judge_relevance 轻量检索
            [{"content": "真实内容", "source": "a.md", "title": "A", "score": 0.9}],  # rag_retrieve
        ]

        final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 25})

    # 幻觉 → quality_fail → 写 quality_warning，不覆盖 final_answer
    assert final_state.get("has_hallucination") is True
    assert "编造的答案" in final_state.get("final_answer", "")  # 原答案保留
    assert "quality_warning" in final_state
    assert "未经验证" in final_state["quality_warning"]


@pytest.mark.asyncio
async def test_build_graph_rag_quality_fail_routes_to_web_search():
    """验证 CRAG 回路：RAG 质量评估不通过 → query_corrector → 重试检索 → 仍失败 → web_search。

    对应测试报告路径 B（升级为 CRAG：纠正一次再放弃）。
    """
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)

    initial_state = {
        "query": "RAG 不足测试",
        "conversation_id": "topo-crag-test",
        "history": [],
        "judge_log": [],
    }

    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval, \
         patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.tavily_search", new_callable=AsyncMock) as mock_ts:
        mock_llm.side_effect = [
            {"text": "RAG 不足测试", "structured": None},  # rewrite_query
            {"text": "", "structured": {"is_chitchat": False, "needs_decomposition": False, "reasoning_steps": []}},  # decompose
            {"text": "RAG 检索", "structured": None},  # query_corrector（CRAG 纠正）
            {"text": "联网答案", "structured": None},  # generate_online
            {"text": "", "structured": {"has_hallucination": False, "answer_quality_pass": True, "reason": "ok"}},  # combined_quality_check
        ]
        # judge_relevance: 高分短路 relevant=true
        # rag_retrieve 第一次: 低分（触发 CRAG）
        # rag_retrieve 第二次: 仍低分（第二次失败 → web_search）
        mock_ret.side_effect = [
            [{"content": "相关", "source": "a.md", "title": "A", "score": 0.9}],  # judge_relevance 轻量检索
            [{"content": "不相关内容", "source": "b.md", "title": "B", "score": 0.1}],  # rag_retrieve 第一次（低分）
            [{"content": "仍不相关", "source": "c.md", "title": "C", "score": 0.15}],  # rag_retrieve 第二次（CRAG 回路，仍低分）
        ]
        mock_ts.return_value = "[1] 联网内容"

        final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 25})

    # CRAG 纠正一次后仍失败 → 走 online 路径
    assert final_state.get("route_path") == "online"
    assert "联网答案" in final_state.get("final_answer", "")
    # 验证 CRAG 回路执行：correction_count=1（纠正过一次）
    assert final_state.get("correction_count") == 1
