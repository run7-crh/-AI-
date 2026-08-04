# backend/app/graph/nodes.py
"""LangGraph 节点定义（对齐 Dify 工作流）。

工作流拓扑（12 节点 + 5 路由函数）：
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
               │               └─ fail → web_search → generate_online → combined_quality_check
               └─ not_relevant → web_search → generate_online → combined_quality_check
                                                              ├─ pass → END
                                                              └─ fail → quality_fail → END

关键设计：
- decompose_question：意图分类 + 问题分解（P0-2 恢复，P1-5 闲聊快速通道）
- combined_quality_check：合并幻觉检测+答案质量评估（P1-1 合并，省 1 次 LLM 调用）
- rag_quality_eval：reranker 分数阈值短路（P1-2，高分/低分跳过 LLM）
- quality_fail：保留原始答案 + 附加 quality_warning（P1-3，不覆盖 final_answer）
"""
import logging

from langchain_core.runnables import RunnableConfig

from app.graph.state import AgentState
from app.graph.tools import call_llm, evaluate, retrieve, tavily_search, CombinedQualitySchema, DecomposeSchema
from app.graph.prompts import (
    REWRITE_PROMPT,
    DECOMPOSE_PROMPT,
    LOCAL_GEN_PROMPT,
    ONLINE_GEN_PROMPT,
    CHITCHAT_PROMPT,
    MULTI_STEP_PROMPT,
    QUERY_CORRECTOR_PROMPT,
    IS_COMBINED_QUALITY_PROMPT,
)
from app.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# 节点 1：意图改写
# ============================================================================
async def rewrite_query_node(state: AgentState) -> dict:
    """问题改写节点（对齐 Dify 节点 1784708937350）。

    P1-4: 不传 history（避免 LLM 基于 history 生成答案而非改写 query）。
    P1-4: 强化容错——输出异常（超长/多行/含标题/含列表标记）时退回原始 query。
    """
    result = await call_llm(
        system_prompt=REWRITE_PROMPT.format(query=state["query"]),
        user_input=state["query"],
        temperature=0.7,
        model=settings.MODEL_FLASH,
    )
    rewritten = result["text"].strip()
    # P1-4: 容错——LLM 输出疑似答案/解释而非改写时退回原始 query
    # 检测维度：超长 / 多行 / Markdown 标题 / Markdown 列表标记 / 代码块
    is_abnormal = (
        len(rewritten) > 200
        or "\n" in rewritten
        or rewritten.startswith("#")
        or rewritten.startswith("- ")
        or rewritten.startswith("* ")
        or rewritten.startswith("```")
        # 数字列表："1. xxx" 或 "1) xxx"
        or (len(rewritten) >= 2 and rewritten[0].isdigit() and rewritten[1] in ".)")
    )
    if is_abnormal:
        logger.warning(
            f"rewrite_query 输出异常，退回原始 query。输出前 100 字: {rewritten[:100]!r}"
        )
        return {"rewritten_query": state["query"]}
    return {"rewritten_query": rewritten}


# ============================================================================
# 节点 1.5：意图分类 + 问题分解（decompose_question）
# ============================================================================
async def decompose_question_node(state: AgentState) -> dict:
    """意图分类 + 问题分解（P0-2 + P1-5）。

    判断问题类型：
    - is_chitchat=true → 闲聊快速通道，直达 generate_local
    - needs_decomposition=true → 多步推理，走 multi_step_reason
    - else → 正常流程，走 judge_relevance
    """
    result = await call_llm(
        system_prompt=DECOMPOSE_PROMPT.format(query=state["rewritten_query"]),
        user_input=state["rewritten_query"],
        temperature=0.3,
        output_schema=DecomposeSchema,
        model=settings.MODEL_FLASH,
    )
    structured = result["structured"]
    return {
        "is_chitchat": structured["is_chitchat"],
        "needs_decomposition": structured["needs_decomposition"],
        "reasoning_steps": structured.get("reasoning_steps", []),
    }


# ============================================================================
# 节点 2：问题相关性判断（轻量检索 + 阈值短路）
# ============================================================================
# 轻量检索阈值：top_k=1 的 reranker 分数 >= 此值直接判 relevant，跳过 LLM
# 修复测试报告 🔴 严重问题：LLM 把"什么是RAG"误判为通用知识 → false
# 改为用检索器实测"知识库里有没有相关内容"，比 LLM 猜测更可靠
RELEVANCE_SCORE_THRESHOLD = 0.5
# P1-4: 完整检索 avg_reranker_score 阈值，低分路径二次确认
RELEVANCE_AVG_SCORE_THRESHOLD = 0.4

# 时效性/市场数据关键词：命中则跳过检索短路，强制走 LLM 判断
# 依据：query_log 中 2 条 useless 反馈 + eval q005 route_wrong 均为时效性问题被误短路
TIME_SENSITIVE_KEYWORDS = (
    "最新", "今天", "当前", "现在", "最近", "2024", "2025", "2026",
    "性能最强", "最好", "排名", "跑分", "市场", "主流有哪些",
    "发布", "上线", "早于",
)


def _is_time_sensitive(query: str) -> bool:
    """检测问题是否含时效性/市场数据关键词，这类问题即使检索到相关文档也不能短路为 local。"""
    return any(kw in query for kw in TIME_SENSITIVE_KEYWORDS)


async def judge_relevance_node(state: AgentState, rag_retriever) -> dict:
    """判断问题是否与知识库相关（对齐 Dify 节点 1785000000001）。

    修复方案：轻量检索 + 阈值短路 + 完整检索兜底 + LLM 兜底
    1. 先用 rewritten_query 做轻量检索（top_k=1）
    2. reranker 分数 >= 0.5 → 直接判 relevant=true（跳过 LLM，省 1 次调用）
    3. P1-4: 低分时做完整检索（top_k=3），avg_score >= 0.4 直接判相关
    4. 仍低分或无结果 → 用 LLM 判断（原始 query，避免被改写影响）

    为什么用 rewritten_query 检索：检索器需要完整问题（含指代消解后的实体）
    为什么用原始 query 给 LLM：LLM 判断相关性看问题本身，改写可能引入偏差
    """
    # 时效性检查：命中关键词的问题跳过所有检索短路，强制走 LLM 判断
    # 依据：query_log 中 2 条 useless + eval q005 均为时效性问题被检索短路误判为 local
    if _is_time_sensitive(state["query"]):
        logger.info(
            f"judge_relevance 跳过短路（时效性关键词命中）, 直接走 LLM 判断: query={state['query']!r}"
        )
        light_result = []
    else:
        # 步骤 1：轻量检索
        try:
            light_result = await retrieve(state["rewritten_query"], rag_retriever, top_k=1)
        except Exception as e:
            logger.warning(f"judge_relevance 轻量检索失败，降级到 LLM 判断: {e}")
            light_result = []

    # 步骤 2：高分短路
    if light_result:
        top_score = light_result[0].get("score", 0)
        if top_score >= RELEVANCE_SCORE_THRESHOLD:
            logger.info(
                f"judge_relevance 短路通过: top_score={top_score:.4f} >= {RELEVANCE_SCORE_THRESHOLD} "
                f"source={light_result[0].get('source', '?')}"
            )
            return {
                "is_relevant": True,
                "judge_log": [{
                    "judge_type": "is_relevant",
                    "passed": True,
                    "raw_output": {
                        "reason": f"轻量检索高分短路 (score={top_score:.4f})",
                        "method": "light_retrieval",
                        "top_score": top_score,
                        "source": light_result[0].get("source", "?"),
                    },
                }],
            }
        logger.info(
            f"judge_relevance 轻量检索低分: top_score={top_score:.4f} < {RELEVANCE_SCORE_THRESHOLD}, "
            f"P1-4: 降级到完整检索"
        )
    else:
        logger.info("judge_relevance 轻量检索无结果, P1-4: 降级到完整检索")

    # P1-4: 步骤 3：完整检索（top_k=3），用 avg_reranker_score 二次确认
    # 时效性问题已跳过短路，此处仍执行完整检索但不会短路（light_result 为空 → 进入此分支）
    # 但为防止时效性问题被完整检索短路误判，此处也跳过
    if _is_time_sensitive(state["query"]):
        full_result = []
        logger.info("judge_relevance 时效性问题跳过完整检索短路, 直接走 LLM 判断")
    else:
        try:
            full_result = await retrieve(state["rewritten_query"], rag_retriever, top_k=3)
        except Exception as e:
            logger.warning(f"judge_relevance 完整检索失败，降级到 LLM 判断: {e}")
            full_result = []

    if full_result:
        avg_score = sum(r.get("score", 0) for r in full_result) / len(full_result)
        if avg_score >= RELEVANCE_AVG_SCORE_THRESHOLD:
            logger.info(
                f"judge_relevance 完整检索确认相关: avg_score={avg_score:.4f} >= {RELEVANCE_AVG_SCORE_THRESHOLD}"
            )
            return {
                "is_relevant": True,
                "judge_log": [{
                    "judge_type": "is_relevant",
                    "passed": True,
                    "raw_output": {
                        "reason": f"完整检索 avg_score 短路 (score={avg_score:.4f})",
                        "method": "full_retrieval",
                        "avg_score": avg_score,
                    },
                }],
            }
        logger.info(
            f"judge_relevance 完整检索仍低分: avg_score={avg_score:.4f} < {RELEVANCE_AVG_SCORE_THRESHOLD}, "
            f"降级到 LLM 判断"
        )
    else:
        logger.info("judge_relevance 完整检索无结果, 降级到 LLM 判断")

    # 步骤 4：仍低分或无结果，用 LLM 判断（原始 query）
    result = await evaluate(
        judge_type="is_relevant",
        source="",
        query=state["query"],
    )
    return {"is_relevant": result["passed"], "judge_log": [result]}


# ============================================================================
# 节点 3：RAG 检索
# ============================================================================
async def rag_retrieve_node(state: AgentState, rag_retriever) -> dict:
    """知识库检索（对齐 Dify 节点 1784562227367）。"""
    retrieval_result = await retrieve(state["rewritten_query"], rag_retriever)

    if retrieval_result:
        scores = [round(r.get("score", 0), 4) for r in retrieval_result]
        sources = [r.get("source", "?") for r in retrieval_result]
        # P1-2: 计算 reranker 平均分用于质量评估短路
        avg_score = sum(r.get("score", 0) for r in retrieval_result) / len(retrieval_result)
        logger.info(
            f"rag_retrieve query={state['rewritten_query']!r} "
            f"hits={len(retrieval_result)} avg_score={avg_score:.4f} "
            f"scores={scores} sources={sources}"
        )
    else:
        avg_score = 0.0
        logger.warning(f"rag_retrieve query={state['rewritten_query']!r} 检索结果为空")

    return {
        "retrieval_result": retrieval_result,
        "avg_reranker_score": avg_score,
    }


# ============================================================================
# 节点 4：RAG 质量评估
# ============================================================================
# P1-2: reranker 分数阈值，灰色地带才调 LLM
RERANKER_SCORE_HIGH = 0.7  # 高于此值直接判定通过
RERANKER_SCORE_LOW = 0.3   # 低于此值直接判定不通过


async def rag_quality_eval_node(state: AgentState) -> dict:
    """检索质量评估（对齐 Dify 节点 1785100000001）。

    P1-2: 先按 reranker 平均分短路判断：
    - avg_score > 0.7 → 直接通过（省 1 次 LLM 调用）
    - avg_score < 0.3 → 直接不通过（省 1 次 LLM 调用）
    - 0.3 <= avg_score <= 0.7 → 灰色地带，调 LLM 精细判断
    检索结果为空时直接不通过。
    """
    retrieval_result = state.get("retrieval_result", [])
    if not retrieval_result:
        logger.info("rag_quality_eval 空检索结果，直接判定不通过")
        return {
            "rag_quality_pass": False,
            "judge_log": [{"judge_type": "is_retrieval_quality", "passed": False,
                           "raw_output": {"reason": "empty retrieval", "short_circuit": "empty"}}],
        }

    avg_score = state.get("avg_reranker_score", 0.0)

    # P1-2: 高分短路通过
    if avg_score > RERANKER_SCORE_HIGH:
        logger.info(f"rag_quality_eval 短路通过 avg_score={avg_score:.4f} > {RERANKER_SCORE_HIGH}")
        return {
            "rag_quality_pass": True,
            "judge_log": [{"judge_type": "is_retrieval_quality", "passed": True,
                           "raw_output": {"reason": "high reranker score", "short_circuit": "high",
                                          "avg_score": avg_score}}],
        }

    # P1-2: 低分短路不通过
    if avg_score < RERANKER_SCORE_LOW:
        logger.info(f"rag_quality_eval 短路不通过 avg_score={avg_score:.4f} < {RERANKER_SCORE_LOW}")
        return {
            "rag_quality_pass": False,
            "judge_log": [{"judge_type": "is_retrieval_quality", "passed": False,
                           "raw_output": {"reason": "low reranker score", "short_circuit": "low",
                                          "avg_score": avg_score}}],
        }

    # 灰色地带：调 LLM 精细判断
    source_text = "\n\n".join([r["content"] for r in retrieval_result])
    quality_judge = await evaluate(
        judge_type="is_retrieval_quality",
        source=source_text,
        query=state["rewritten_query"],
    )
    logger.info(
        f"rag_quality_eval LLM 判断 avg_score={avg_score:.4f}（灰色地带） "
        f"passed={quality_judge['passed']} "
        f"reason={quality_judge.get('raw_output', {}).get('reason', '')!r}"
    )
    return {
        "rag_quality_pass": quality_judge["passed"],
        "judge_log": [quality_judge],
    }


# ============================================================================
# 节点 4.5：查询纠正（CRAG 回路）
# ============================================================================
# CRAG: 检索失败后二次改写查询，再重试检索一次。
# 与首次 rewrite_query 职责不同：首次解决指代消解/补上下文，
# 此处解决"检索方向错误"，且把失败原因回传给 LLM 帮助纠正。
# 用 correction_count 上限 1 次防死循环（路由函数在 >=1 时强制跳 web_search）。
async def query_corrector_node(state: AgentState) -> dict:
    """CRAG 查询纠正节点：基于上次失败原因重新组织检索词。

    从 judge_log 最后一条提取 failure_reason，调用 LLM 改写 rewritten_query，
    递增 correction_count。容错策略与 rewrite_query_node 一致（异常时保留原查询）。
    """
    # 提取上次评估的失败原因
    last_judge = state.get("judge_log", [])[-1] if state.get("judge_log") else None
    if last_judge:
        raw = last_judge.get("raw_output", {})
        failure_reason = raw.get("reason", "检索质量评估未通过")
    else:
        failure_reason = "检索质量评估未通过"

    try:
        result = await call_llm(
            system_prompt=QUERY_CORRECTOR_PROMPT.format(
                query=state["rewritten_query"],
                failure_reason=failure_reason,
            ),
            user_input=state["rewritten_query"],
            temperature=0.7,
            model=settings.MODEL_FLASH,
        )
        corrected = result["text"].strip()
        # 容错：与 rewrite_query_node 一致的异常检测
        is_abnormal = (
            len(corrected) > 200
            or "\n" in corrected
            or corrected.startswith("#")
            or corrected.startswith("- ")
            or corrected.startswith("* ")
            or corrected.startswith("```")
            or (len(corrected) >= 2 and corrected[0].isdigit() and corrected[1] in ".)")
        )
        if is_abnormal:
            logger.warning(f"query_corrector 输出异常，保留原查询。输出前 100 字: {corrected[:100]!r}")
            corrected = state["rewritten_query"]
    except Exception as e:
        logger.error(f"query_corrector 调用失败，保留原查询: {e}")
        corrected = state["rewritten_query"]

    logger.info(
        f"CRAG 查询纠正: '{state['rewritten_query']}' → '{corrected}' "
        f"(failure_reason={failure_reason!r}, correction_count={state.get('correction_count', 0) + 1})"
    )
    return {
        "rewritten_query": corrected,
        "correction_count": state.get("correction_count", 0) + 1,
    }


# ============================================================================
# 节点 5：联网搜索
# ============================================================================
async def web_search_node(state: AgentState) -> dict:
    """Tavily 联网搜索（对齐 Dify 节点 1784709583735）。"""
    result = await tavily_search(state["rewritten_query"])
    return {"web_search_result": result}


# ============================================================================
# 节点 6a：闲聊快速通道（P1-6: 从 generate_local 拆分）
# ============================================================================
async def chitchat_node(state: AgentState, config: RunnableConfig) -> dict:
    """闲聊快速通道，用 CHITCHAT_PROMPT 直接回答，不需要 retrieval_result。"""
    try:
        result = await call_llm(
            system_prompt=CHITCHAT_PROMPT.format(query=state["query"]),
            user_input=state["query"],
            temperature=0.7,
            history=state.get("history", []),
            model=settings.MODEL_PRO_CHAT,
            stream=True,
            config=config,
        )
        return {"final_answer": result["text"], "route_path": "chitchat"}
    except Exception as e:
        logger.error(f"chitchat 生成失败: {e}")
        return {"final_answer": "你好，有什么可以帮助你的吗？", "route_path": "chitchat"}


# ============================================================================
# 节点 6b：本地生成答案（P1-6: 移除 is_chitchat 分支，只处理知识库问答）
# ============================================================================
async def generate_local_node(state: AgentState, config: RunnableConfig) -> dict:
    """基于知识库内容生成答案（对齐 Dify 节点 1784711392079）。

    call_llm 已有 retry（3 次），此处降级兜底。
    """
    context = "\n\n".join([
        f"[来源：文档片段 {i+1}] {r['content']}"
        for i, r in enumerate(state["retrieval_result"])
    ])
    prompt = LOCAL_GEN_PROMPT.format(
        query=state["rewritten_query"],
        context=context,
    )
    try:
        result = await call_llm(
            system_prompt=prompt,
            user_input=state["query"],
            temperature=0.7,
            history=state.get("history", []),
            model=settings.MODEL_PRO_CHAT,
            stream=True,
            config=config,
        )
        return {
            "final_answer": result["text"],
            "route_path": "local",
        }
    except Exception as e:
        logger.error(f"generate_local LLM 调用失败（retry 已耗尽）: {e}")
        return {
            "final_answer": f"抱歉，生成回答时遇到问题（{type(e).__name__}），请稍后重试。",
            "route_path": "local",
        }


# ============================================================================
# 节点 7：联网生成答案
# ============================================================================
async def generate_online_node(state: AgentState, config: RunnableConfig) -> dict:
    """基于搜索结果生成答案（对齐 Dify 节点 1784713973176）。

    call_llm 已有 retry（3 次），此处降级兜底。
    P2 优化：检测搜索失败，设置 quality_warning 提示用户。
    """
    search_result = state["web_search_result"]
    # 检测搜索失败标识（tavily_search 失败时返回的提示字符串）
    search_failed = (
        search_result.startswith("（联网搜索失败")
        or search_result.startswith("（联网搜索未返回结果")
    )
    quality_warning = None
    if search_failed:
        quality_warning = "联网搜索失败，已基于有限信息生成回答，建议稍后重试"
        logger.warning(f"generate_online 搜索失败兜底: query={state['query']!r}")

    prompt = ONLINE_GEN_PROMPT.format(
        query=state["rewritten_query"],
        search_result=search_result,
    )
    try:
        result = await call_llm(
            system_prompt=prompt,
            user_input=state["query"],
            temperature=0.7,
            history=state.get("history", []),
            model=settings.MODEL_PRO_CHAT,
            stream=True,
            config=config,
        )
        return {
            "final_answer": result["text"],
            "route_path": "online",
            "quality_warning": quality_warning,
        }
    except Exception as e:
        logger.error(f"generate_online LLM 调用失败（retry 已耗尽）: {e}")
        return {
            "final_answer": f"抱歉，生成回答时遇到问题（{type(e).__name__}），请稍后重试。",
            "route_path": "online",
            "quality_warning": quality_warning,
        }


# ============================================================================
# 节点 6.5：多步推理（multi_step_reason）
# ============================================================================
async def multi_step_reason_node(state: AgentState, config: RunnableConfig, rag_retriever=None) -> dict:
    """多步推理节点（P0-2: 恢复多步推理能力）。

    使用 deepseek-reasoner 对分解的子问题逐步推理。
    对每个子问题调用 RAG 检索，将检索内容注入 prompt。
    """
    sub_queries = state.get("reasoning_steps", [])
    sub_query_texts = [sq.get("sub_query", "") for sq in sub_queries]

    # P1-3: 子问题去重 + 数量限制（最多 5 个，避免 context 过长）
    seen = set()
    deduped = []
    for sq in sub_query_texts:
        key = sq.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(sq)
    sub_query_texts = deduped[:5]
    sub_queries_text = "\n".join([f"{i+1}. {sq}" for i, sq in enumerate(sub_query_texts)])

    # 对每个子问题调用 RAG 检索，保留原始 source 字段（修复 multi_hop 引用正确率 0% 问题）
    all_results = []  # 存所有子问题的检索结果（含 source）
    if rag_retriever:
        for sq in sub_query_texts:
            if sq:
                results = await retrieve(sq, rag_retriever)
                all_results.extend(results)

    # 去重：同一文档可能被多个子问题检索到，按 (source, content 前 100 字) 去重
    seen_keys = set()
    deduped_results = []
    for r in all_results:
        key = (r.get("source", ""), r.get("content", "")[:100])
        if key not in seen_keys:
            seen_keys.add(key)
            deduped_results.append(r)

    # context 带文档名编号，便于 LLM 用 [来源：文档名] 标注（修复 q009 疑似幻觉问题）
    if deduped_results:
        context_parts = [
            f"【文档：{r.get('source', '未知')}】\n{r.get('content', '')}"
            for r in deduped_results
        ]
        context = "\n\n".join(context_parts)
    else:
        context = "（无相关知识库内容）"

    prompt = MULTI_STEP_PROMPT.format(
        sub_queries=sub_queries_text,
        context=context,
        query=state["query"],
    )
    try:
        result = await call_llm(
            system_prompt=prompt,
            user_input=state["query"],
            temperature=0.5,
            history=state.get("history", []),
            model=settings.MODEL_PRO_REASON,
            stream=True,
            config=config,
        )
        return {
            "final_answer": result["text"],
            "route_path": "decomposition",
            # 保留原始 source 字段，供 meta 事件 sources 聚合 + 评估脚本校验引用正确率
            "retrieval_result": deduped_results,
        }
    except Exception as e:
        logger.error(f"multi_step_reason LLM 调用失败（retry 已耗尽）: {e}")
        return {
            "final_answer": f"抱歉，推理过程中遇到问题（{type(e).__name__}），请稍后重试。",
            "route_path": "decomposition",
        }


# ============================================================================
# 节点 8：合并质量评估（幻觉检测 + 答案质量，P1-1 合并）
# ============================================================================
async def combined_quality_check_node(state: AgentState) -> dict:
    """合并质量评估（P1-1: 替代 hallucination_check + answer_quality_eval）。

    一次 LLM 调用同时评估幻觉和答案质量，每次请求从 6 次降到 5 次。
    source 根据 route_path 取对应源材料（同时解决 P1-6 联网传 source）。
    """
    try:
        route_path = state.get("route_path", "local")
        if route_path == "online":
            source_text = state.get("web_search_result", "")
        else:
            # local / decomposition 都用 retrieval_result 作为 source
            # - local: 标准检索结果
            # - decomposition: multi_step_reason_node 写入的各子问题检索内容
            # chitchat 不会走到这里（chitchat_node → END 跳过 combined_quality_check）
            source = state.get("retrieval_result", [])
            source_text = "\n\n".join([r["content"] for r in source]) if source else ""
        # P1-11: source 截断，避免 prompt 过长浪费 token（保留前 2000 字）
        if len(source_text) > 2000:
            source_text = source_text[:2000] + "\n...(源材料已截断)"
        answer = state["final_answer"]

        result = await call_llm(
            system_prompt=IS_COMBINED_QUALITY_PROMPT.format(
                source=source_text, answer=answer, query=state["rewritten_query"],
            ),
            user_input=state["rewritten_query"] or "请评估",
            temperature=0.2,
            output_schema=CombinedQualitySchema,
            model=settings.MODEL_FLASH,
        )
        structured = result["structured"]
        return {
            "has_hallucination": structured["has_hallucination"],
            "answer_quality_pass": structured["answer_quality_pass"],
            "judge_log": [{
                "judge_type": "combined_quality",
                "passed": not structured["has_hallucination"] and structured["answer_quality_pass"],
                "raw_output": structured,
            }],
        }
    except Exception as e:
        logger.warning(f"合并质量评估失败，降级到不通过: {e}")
        return {
            "has_hallucination": True,
            "answer_quality_pass": False,
            "judge_log": [{
                "judge_type": "combined_quality",
                "passed": False,
                "raw_output": {"error": str(e)},
            }],
        }


# ============================================================================
# 节点 10：质量不合格
# ============================================================================
async def quality_fail_node(state: AgentState) -> dict:
    """质量不合格提示节点（对齐 Dify 节点 1785054743478 / 1785054896593）。

    P1-3: 不再覆盖 final_answer，改为设置 quality_warning 警告文本。
    保留 LLM 生成的原始答案，让用户看到内容并自行判断，
    前端在答案上方展示黄色警告横幅。

    P1-13: 走到本节点必然是 has_hallucination 或 answer_quality_pass=False，
    简化为 if/else 两路判断，删除原 else 兜底常量。
    """
    if state.get("has_hallucination"):
        warning = "⚠️ 检测到答案可能包含未经验证的信息，请谨慎参考。"
    else:
        warning = "⚠️ 答案质量评估未通过，可能未充分回答问题，建议重新表述提问。"

    return {"quality_warning": warning}
