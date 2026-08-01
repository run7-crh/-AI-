# backend/app/graph/builder.py
"""LangGraph 图构建（对齐 Dify 工作流）。

工作流拓扑（13 节点 + 5 路由函数，含 CRAG 回路）：
  rewrite_query → decompose_question
    ├─ is_chitchat → chitchat_node → END
    ├─ needs_decomposition → multi_step_reason → combined_quality_check
    │                                          ├─ pass → END
    │                                          └─ fail → quality_fail → END
    └─ else → judge_relevance
               ├─ relevant → rag_retrieve → rag_quality_eval
               │               ├─ pass → generate_local → combined_quality_check
               │               │                            ├─ pass → END
               │               │                            └─ fail → quality_fail → END
               │               └─ fail → query_corrector → rag_retrieve → rag_quality_eval
               │                          (correction_count < 1)      ├─ pass → generate_local → ...
               │                                                        └─ fail → web_search → generate_online → ...
               └─ not_relevant → web_search → generate_online → combined_quality_check
                                                              ├─ pass → END
                                                              └─ fail → quality_fail → END

CRAG 回路（Self-RAG/CRAG 论文精神）：
- rag_quality_eval 失败时，不直接放弃走 web_search，而是先纠正查询重试一次检索
- correction_count 上限 1 次，第二次仍失败才走 web_search
- query_corrector 职责不同于首次 rewrite_query：解决"检索方向错误"，回传失败原因

路由函数：
- route_after_decompose：chitchat_node / needs_decomposition / judge_relevance
- route_after_relevance：rag_retrieve / web_search
- route_after_rag_quality：generate_local / query_corrector / web_search
- route_after_generate：combined_quality_check（chitchat 已拆分到独立节点）
- route_after_combined_quality：END / quality_fail
"""
from functools import partial
from langgraph.graph import StateGraph, END

from app.graph.state import AgentState
from app.graph.nodes import (
    rewrite_query_node,
    decompose_question_node,
    chitchat_node,
    judge_relevance_node,
    rag_retrieve_node,
    rag_quality_eval_node,
    query_corrector_node,
    web_search_node,
    generate_local_node,
    generate_online_node,
    multi_step_reason_node,
    combined_quality_check_node,
    quality_fail_node,
)


def route_after_relevance(state):
    """相关性判断后路由：相关 → RAG检索，不相关 → 联网搜索。"""
    return "rag_retrieve" if state.get("is_relevant") else "web_search"


def route_after_rag_quality(state):
    """RAG质量评估后路由（CRAG 回路）：
    - pass → generate_local
    - fail + correction_count < 1 → query_corrector（重试一次检索）
    - fail + correction_count >= 1 → web_search（第二次仍失败才放弃）
    """
    if state.get("rag_quality_pass"):
        return "generate_local"
    if state.get("correction_count", 0) < 1:
        return "query_corrector"
    return "web_search"


def route_after_decompose(state):
    """意图分类后路由：chitchat → chitchat_node，decomposition → multi_step_reason，else → judge_relevance。"""
    if state.get("is_chitchat"):
        return "chitchat_node"
    if state.get("needs_decomposition"):
        return "multi_step_reason"
    return "judge_relevance"


def route_after_generate(state):
    """generate_local/generate_online 生成后统一进质量评估。"""
    return "combined_quality_check"


def route_after_combined_quality(state):
    """合并质量评估后路由：无幻觉且质量通过 → 结束，否则 → 质量不合格。"""
    if not state.get("has_hallucination") and state.get("answer_quality_pass"):
        return END
    return "quality_fail"


def build_graph(rag_retriever):
    """构建 LangGraph 工作流。

    rag_retriever 通过 functools.partial 注入到 rag_retrieve_node，
    保持 async 性质（lambda 包装 async 函数会返回 coroutine，LangGraph 不会 await）。
    """
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("rewrite_query", rewrite_query_node)
    graph.add_node("decompose_question", decompose_question_node)
    graph.add_node("chitchat_node", chitchat_node)
    # judge_relevance 需注入 rag_retriever：用于轻量检索（top_k=1）+ 阈值短路
    graph.add_node("judge_relevance", partial(judge_relevance_node, rag_retriever=rag_retriever))
    graph.add_node("rag_retrieve", partial(rag_retrieve_node, rag_retriever=rag_retriever))
    graph.add_node("rag_quality_eval", rag_quality_eval_node)
    graph.add_node("query_corrector", query_corrector_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("generate_local", generate_local_node)
    graph.add_node("generate_online", generate_online_node)
    graph.add_node("multi_step_reason", partial(multi_step_reason_node, rag_retriever=rag_retriever))
    graph.add_node("combined_quality_check", combined_quality_check_node)
    graph.add_node("quality_fail", quality_fail_node)

    # 入口
    graph.set_entry_point("rewrite_query")

    # 边：rewrite_query → decompose_question
    graph.add_edge("rewrite_query", "decompose_question")

    # 边：decompose_question → chitchat_node / multi_step_reason / judge_relevance
    graph.add_conditional_edges(
        "decompose_question",
        route_after_decompose,
        {
            "chitchat_node": "chitchat_node",
            "multi_step_reason": "multi_step_reason",
            "judge_relevance": "judge_relevance",
        },
    )

    # P1-6: chitchat_node → END（闲聊直接结束，跳过质量评估）
    graph.add_edge("chitchat_node", END)

    # 边：judge_relevance → rag_retrieve / web_search（条件路由）
    graph.add_conditional_edges(
        "judge_relevance",
        route_after_relevance,
        {"rag_retrieve": "rag_retrieve", "web_search": "web_search"},
    )

    # 边：rag_retrieve → rag_quality_eval
    graph.add_edge("rag_retrieve", "rag_quality_eval")

    # 边：rag_quality_eval → generate_local / query_corrector / web_search（CRAG 条件路由）
    graph.add_conditional_edges(
        "rag_quality_eval",
        route_after_rag_quality,
        {
            "generate_local": "generate_local",
            "query_corrector": "query_corrector",
            "web_search": "web_search",
        },
    )

    # CRAG 回路：query_corrector → rag_retrieve（重试检索）
    graph.add_edge("query_corrector", "rag_retrieve")

    # 边：web_search → generate_online
    graph.add_edge("web_search", "generate_online")

    # P1-6: generate_local → combined_quality_check（chitchat 已拆分到独立节点）
    graph.add_edge("generate_local", "combined_quality_check")
    # 边：generate_online → combined_quality_check
    graph.add_edge("generate_online", "combined_quality_check")
    # 边：multi_step_reason → combined_quality_check
    graph.add_edge("multi_step_reason", "combined_quality_check")

    # 边：combined_quality_check → END / quality_fail（条件路由）
    graph.add_conditional_edges(
        "combined_quality_check",
        route_after_combined_quality,
        {END: END, "quality_fail": "quality_fail"},
    )

    # 边：quality_fail → END
    graph.add_edge("quality_fail", END)

    return graph.compile()
