# backend/app/graph/builder.py
"""LangGraph 图构建（对齐 Dify 工作流）。

工作流拓扑（14 节点 + 5 路由函数，含 CRAG 回路与追问快速通道）：
  rewrite_query → decompose_question
    ├─ is_chitchat → chitchat_node → END
    ├─ 信息不足（AGENT_FOLLOWUP_ENABLED 且守卫通过）→ ask_followup → END
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
# 导入 partial，用于把额外参数（如检索器）预绑定到节点函数上进行注入
from functools import partial
# 导入 LangGraph 的状态图与结束标记
from langgraph.graph import StateGraph, END

# 导入工作流状态类型定义
from app.graph.state import AgentState
from app.config import settings
# 导入所有图节点函数
from app.graph.nodes import (
    rewrite_query_node,            # 意图改写节点
    decompose_question_node,       # 意图分类+分解节点
    chitchat_node,                 # 闲聊节点
    ask_followup_node,             # 阶段 3: 主动追问节点（信息不足快速通道）
    judge_relevance_node,          # 相关性判断节点
    rag_retrieve_node,             # RAG 检索节点
    rag_quality_eval_node,         # 检索质量评估节点
    query_corrector_node,          # 查询纠正节点
    web_search_node,               # 联网搜索节点
    generate_local_node,           # 本地生成节点
    generate_online_node,          # 联网生成节点
    multi_step_reason_node,        # 多步推理节点
    combined_quality_check_node,   # 合并质量评估节点
    quality_fail_node,             # 质量不合格节点
    _should_followup,              # 阶段 3: 追问守卫（路由用）
)


# 定义相关性判断后的路由函数
def route_after_relevance(state):
    """相关性判断后路由：相关 → RAG检索，不相关 → 联网搜索。"""
    return "rag_retrieve" if state.get("is_relevant") else "web_search"  # 按是否相关指向节点


# 定义 RAG 质量评估后的路由函数（含 CRAG 回路）
def route_after_rag_quality(state):
    """RAG质量评估后路由（CRAG 回路）：
    - pass → generate_local
    - fail + correction_count < 1 → query_corrector（重试一次检索）
    - fail + correction_count >= 1 → web_search（第二次仍失败才放弃）
    """
    if state.get("rag_quality_pass"):        # 检索质量通过
        return "generate_local"              # 走本地生成
    if state.get("correction_count", 0) < 1: # 失败且纠正次数<1
        return "query_corrector"             # 先纠正查询再重试
    return "web_search"                      # 已纠正过仍失败，转联网搜索


# 定义意图分类后的路由函数
def route_after_decompose(state):
    """意图分类后路由：chitchat → chitchat_node，followup → ask_followup，
    decomposition → multi_step_reason，else → judge_relevance。

    阶段 2: 高风险情形（safety_level=high）覆盖闲聊快速通道——即使被误判为闲聊，
    也必须先检索安全/故障知识再回答，不允许闲聊节点绕过安全处置。
    阶段 3: 信息不足且守卫全部通过时进入主动追问快速通道（AGENT_FOLLOWUP_ENABLED
    开关控制，关闭即回旧行为）；追问优先级低于高风险覆盖（高风险永不追问），
    高于多步分解（_should_followup 要求 needs_decomposition=false）。
    """
    high_risk = state.get("safety_level") == "high" or state.get("safety_flag") is True
    if state.get("is_chitchat") and not high_risk and not state.get("attachment_evidence"):
        # Only the no-attachment greeting path remains lightweight; an
        # explicitly selected attachment must enter the evidence-aware path.
        return "chitchat_node"               # 走闲聊节点
    if settings.AGENT_FOLLOWUP_ENABLED and _should_followup(state):
        return "ask_followup"                # 信息不足 → 主动追问
    # 结构化输出可能出现 needs_decomposition=true 但没有可执行子问题；
    # 此时回到普通相关性判断，避免空 context 直接生成"多步答案"。
    if state.get("needs_decomposition") and any(  # 声称需分解且存在有效子问题
        isinstance(step, dict) and str(step.get("sub_query", "")).strip()  # 子问题是非空字符串
        for step in (state.get("reasoning_steps") or [])  # 遍历子问题
    ):
        return "multi_step_reason"           # 走多步推理
    return "judge_relevance"                 # 否则走普通相关性判断


# 定义生成后的统一路由函数
def route_after_generate(state):
    """generate_local/generate_online 生成后统一进质量评估。"""
    return "combined_quality_check"          # 任何生成节点之后都进合并质量评估


# 定义合并质量评估后的路由函数
def route_after_combined_quality(state):
    """合并质量评估后路由：无幻觉且质量通过 → 结束，否则 → 质量不合格。"""
    if not state.get("has_hallucination") and state.get("answer_quality_pass"):  # 无幻觉且质量通过
        return END                           # 结束工作流
    return "quality_fail"                    # 否则走质量不合格节点


# 定义构建 LangGraph 工作流的函数
def build_graph(rag_retriever):
    """构建 LangGraph 工作流。

    rag_retriever 通过 functools.partial 注入到 rag_retrieve_node，
    保持 async 性质（lambda 包装 async 函数会返回 coroutine，LangGraph 不会 await）。
    """
    graph = StateGraph(AgentState)           # 创建以 AgentState 为状态类型的状态图

    # 添加节点
    graph.add_node("rewrite_query", rewrite_query_node)                    # 意图改写节点
    graph.add_node("decompose_question", decompose_question_node)          # 意图分类+分解节点
    graph.add_node("chitchat_node", chitchat_node)                         # 闲聊节点
    graph.add_node("ask_followup", ask_followup_node)                      # 阶段 3: 主动追问节点
    # judge_relevance 需注入 rag_retriever：用于轻量检索（top_k=1）+ 阈值短路
    graph.add_node("judge_relevance", partial(judge_relevance_node, rag_retriever=rag_retriever))  # 注入检索器
    graph.add_node("rag_retrieve", partial(rag_retrieve_node, rag_retriever=rag_retriever))        # 检索节点
    graph.add_node("rag_quality_eval", rag_quality_eval_node)              # 检索质量评估节点
    graph.add_node("query_corrector", query_corrector_node)                # 查询纠正节点
    graph.add_node("web_search", web_search_node)                          # 联网搜索节点
    graph.add_node("generate_local", generate_local_node)                  # 本地生成节点
    graph.add_node("generate_online", generate_online_node)                # 联网生成节点
    graph.add_node("multi_step_reason", partial(multi_step_reason_node, rag_retriever=rag_retriever))  # 多步推理节点
    graph.add_node("combined_quality_check", combined_quality_check_node)  # 合并质量评估节点
    graph.add_node("quality_fail", quality_fail_node)                      # 质量不合格节点

    # 入口
    graph.set_entry_point("rewrite_query")   # 入口指向意图改写节点

    # 边：rewrite_query → decompose_question
    graph.add_edge("rewrite_query", "decompose_question")  # 改写后进入分解

    # 边：decompose_question → chitchat_node / ask_followup / multi_step_reason / judge_relevance
    graph.add_conditional_edges(             # 条件边（按分类结果分流）
        "decompose_question",                # 起始节点
        route_after_decompose,               # 路由函数
        {
            "chitchat_node": "chitchat_node",      # 闲聊路径
            "ask_followup": "ask_followup",        # 阶段 3: 信息不足追问路径
            "multi_step_reason": "multi_step_reason",  # 多步推理路径
            "judge_relevance": "judge_relevance",  # 普通路径
        },
    )

    # P1-6: chitchat_node → END（闲聊直接结束，跳过质量评估）
    graph.add_edge("chitchat_node", END)     # 闲聊结束工作流

    # 阶段 3: ask_followup → END（追问即本轮最终回答，不检索、不进质量检查）
    graph.add_edge("ask_followup", END)      # 追问结束工作流

    # 边：judge_relevance → rag_retrieve / web_search（条件路由）
    graph.add_conditional_edges(             # 条件边
        "judge_relevance",                   # 起始节点
        route_after_relevance,               # 路由函数
        {"rag_retrieve": "rag_retrieve", "web_search": "web_search"},  # 相关/不相关
    )

    # 边：rag_retrieve → rag_quality_eval
    graph.add_edge("rag_retrieve", "rag_quality_eval")  # 检索后评估质量

    # 边：rag_quality_eval → generate_local / query_corrector / web_search（CRAG 条件路由）
    graph.add_conditional_edges(             # 条件边
        "rag_quality_eval",                  # 起始节点
        route_after_rag_quality,             # 循环路由
        {
            "generate_local": "generate_local",  # 通过→生成
            "query_corrector": "query_corrector",  # 首次失败→纠正
            "web_search": "web_search",          # 再次失败→联网
        },
    )

    # CRAG 回路：query_corrector → rag_retrieve（重试检索）
    graph.add_edge("query_corrector", "rag_retrieve")  # 纠正后回到检索

    # 边：web_search → generate_online
    graph.add_edge("web_search", "generate_online")  # 搜索后联网生成

    # P1-6: generate_local → combined_quality_check（chitchat 已拆分到独立节点）
    graph.add_edge("generate_local", "combined_quality_check")  # 本地生成后评估
    # 边：generate_online → combined_quality_check
    graph.add_edge("generate_online", "combined_quality_check")  # 联网生成后评估
    # 边：multi_step_reason → combined_quality_check
    graph.add_edge("multi_step_reason", "combined_quality_check")  # 多步推理后评估

    # 边：combined_quality_check → END / quality_fail（条件路由）
    graph.add_conditional_edges(             # 条件边
        "combined_quality_check",            # 起始节点
        route_after_combined_quality,        # 路由函数
        {END: END, "quality_fail": "quality_fail"},  # 通过结束/失败告警
    )

    # 边：quality_fail → END
    graph.add_edge("quality_fail", END)      # 质量不合格后结束

    return graph.compile()                   # 编译并返回可执行图
