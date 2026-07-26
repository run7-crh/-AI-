# backend/app/graph/builder.py
from functools import partial
from langgraph.graph import StateGraph, END

from app.graph.state import AgentState
from app.graph.nodes import (
    rewrite_query_node,
    decompose_question_node,
    multi_step_reason_node,
    judge_relevance_node,
    rag_retrieve_node,
    web_search_node,
    generate_answer_node,
    quality_gate_node,
)


def route_after_decompose(state):
    if state.get("needs_decomposition"):
        return "multi_step_reason"
    return "judge_relevance"


def route_after_relevance(state):
    return "rag_retrieve" if state.get("is_relevant") else "web_search"


def route_after_rag_retrieve(state):
    if state.get("rag_quality_pass"):
        return "generate_answer"
    return "web_search"


def route_after_quality(state):
    if state.get("answer_quality_pass") and not state.get("hallucination_flag"):
        return END
    # 质量不通过：local 路径回退联网重新生成，online 路径直接结束（避免无限循环）
    if state.get("route_path") == "local":
        return "fallback_online"
    return END


def build_graph(rag_retriever):
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("rewrite_query", rewrite_query_node)
    graph.add_node("decompose_question", decompose_question_node)
    graph.add_node("multi_step_reason", multi_step_reason_node)
    graph.add_node("judge_relevance", judge_relevance_node)
    # rag_retrieve_node 是 async 函数，签名 (state, rag_retriever)。
    # 用 functools.partial 注入 retriever，保持 async 性质——
    # 若用 lambda 包装 async 函数会返回 coroutine，LangGraph 不会 await 导致
    # InvalidUpdateError: Expected dict, got <coroutine object>.
    graph.add_node("rag_retrieve", partial(rag_retrieve_node, rag_retriever=rag_retriever))
    graph.add_node("web_search", web_search_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("quality_gate", quality_gate_node)
    # fallback_online 复用 web_search 节点逻辑：直接引用同一 async 函数，
    # LangGraph 会正确 await。
    graph.add_node("fallback_online", web_search_node)

    # 入口
    graph.set_entry_point("rewrite_query")

    # 边
    graph.add_edge("rewrite_query", "decompose_question")
    graph.add_conditional_edges(
        "decompose_question",
        route_after_decompose,
        {"multi_step_reason": "multi_step_reason", "judge_relevance": "judge_relevance"},
    )
    # 修复点 1：多步推理直接写 final_answer，主图连到 END
    graph.add_edge("multi_step_reason", END)
    graph.add_conditional_edges(
        "judge_relevance",
        route_after_relevance,
        {"rag_retrieve": "rag_retrieve", "web_search": "web_search"},
    )
    graph.add_conditional_edges(
        "rag_retrieve",
        route_after_rag_retrieve,
        {"generate_answer": "generate_answer", "web_search": "web_search"},
    )
    graph.add_edge("web_search", "generate_answer")
    graph.add_edge("generate_answer", "quality_gate")
    graph.add_conditional_edges(
        "quality_gate",
        route_after_quality,
        {END: END, "fallback_online": "fallback_online"},
    )
    # fallback_online → generate_answer 形成循环
    graph.add_edge("fallback_online", "generate_answer")

    return graph.compile()
