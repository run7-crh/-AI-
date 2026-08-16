# backend/app/api/trace.py
"""思考过程可视化的 trace 工具：节点中文标签、output 白名单提取、reasoning 捞取。

设计依据：docs/superpowers/specs/2026-08-16-trace-visualization-design.md
- 白名单外的 state 字段一律不下发（控制 payload、避免泄露内部 state）
- 长文本截断 200 字符
- judge_log 是 add reducer 累积的，节点粒度只下发最后一条
"""

STAGE_LABELS = {
    "rewrite_query": "正在理解问题...",
    "decompose_question": "正在分析问题类型...",
    "chitchat_node": "正在回应...",
    "judge_relevance": "正在判断问题类型...",
    "rag_retrieve": "正在检索知识库...",
    "rag_quality_eval": "正在评估检索质量...",
    "query_corrector": "正在优化检索词...",
    "web_search": "正在联网搜索...",
    "generate_local": "正在生成回答...",
    "generate_online": "正在生成回答...",
    "multi_step_reason": "正在逐步推理...",
    "combined_quality_check": "正在评估答案质量...",
    "quality_fail": "正在生成提示...",
}


def stage_label(node_name: str) -> str:
    """节点名 → 中文标签（白名单外节点兜底文案）。"""
    return STAGE_LABELS.get(node_name, f"执行: {node_name}")


# 每个节点下发哪些 output 字段（字段名与 graph/nodes.py 实际返回对齐）
TRACE_OUTPUT_FIELDS: dict[str, list[str]] = {
    "rewrite_query": ["rewritten_query"],
    "decompose_question": ["is_chitchat", "needs_decomposition", "reasoning_steps"],
    "judge_relevance": ["is_relevant", "judge_log"],
    "rag_retrieve": ["retrieval_result", "avg_reranker_score"],
    "rag_quality_eval": ["rag_quality_pass", "judge_log"],
    "query_corrector": ["rewritten_query", "correction_count"],
    "web_search": ["web_search_result"],
    "combined_quality_check": [
        "has_hallucination",
        "answer_quality_pass",
        "judge_log",
    ],
    "quality_fail": ["quality_warning"],
}
# chitchat_node / generate_local / generate_online / multi_step_reason
# 无白名单字段（正文走 token 流），仅显示名称+耗时。

_TRUNCATE_LIMIT = 200
_TRUNCATE_LIST_FIELDS = ("retrieval_result", "web_search_result", "reasoning_steps")


def truncate_text(text: str, limit: int = _TRUNCATE_LIMIT) -> str:
    """截断长文本，超限时末尾以省略号标记。非字符串原样返回。"""
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return text[:limit] + "…"


def _truncate_item(item: object) -> object:
    """截断列表内条目：dict 截 content 字段，str 直接截断。"""
    if isinstance(item, dict):
        clipped = dict(item)
        if isinstance(clipped.get("content"), str):
            clipped["content"] = truncate_text(clipped["content"])
        return clipped
    if isinstance(item, str):
        return truncate_text(item)
    return item


def extract_trace_output(node_name: str, output: dict | None) -> dict:
    """按白名单提取节点 output 的关键字段（构建 node_end 事件的 output）。

    - 白名单外的字段一律丢弃
    - judge_log 只取最后一条（当前节点的判断记录）
    - 列表字段（retrieval/web_search/reasoning_steps）内每条截断 200 字
    """
    if not output:
        return {}
    fields = TRACE_OUTPUT_FIELDS.get(node_name)
    if not fields:
        return {}
    result: dict = {}
    for f in fields:
        if f not in output:
            continue
        v = output[f]
        if f == "judge_log":
            if isinstance(v, list) and v:
                result[f] = v[-1]
        elif isinstance(v, list) and f in _TRUNCATE_LIST_FIELDS:
            result[f] = [_truncate_item(item) for item in v]
        else:
            result[f] = v
    return result


def extract_reasoning_content(chunk: object) -> str:
    """从流式 chunk 中提取 deepseek-reasoner 思维链增量，取不到返回空串。

    langchain-openai 把 reasoning_content 放在 additional_kwargs（AIMessageChunk）；
    兼容 dict 形态（含顶层 fallback）。调用方对空串跳过下发。
    """
    if hasattr(chunk, "additional_kwargs"):
        kwargs = chunk.additional_kwargs or {}
        return kwargs.get("reasoning_content") or ""
    if isinstance(chunk, dict):
        kwargs = chunk.get("additional_kwargs") or {}
        return (
            kwargs.get("reasoning_content")
            or chunk.get("reasoning_content")
            or ""
        )
    return ""
