# backend/app/api/trace.py
"""思考过程可视化的 trace 工具：节点中文标签、output 白名单提取、reasoning 捞取。

设计依据：docs/superpowers/specs/2026-08-16-trace-visualization-design.md
- 白名单外的 state 字段一律不下发（控制 payload、避免泄露内部 state）
- 长文本截断 200 字符
- judge_log 是 add reducer 累积的，节点粒度只下发最后一条
"""

# 节点名 → 中文进度标签映射
STAGE_LABELS = {
    "rewrite_query": "正在理解问题...",          # 意图改写
    "decompose_question": "正在分析问题类型...",  # 意图分类+分解
    "chitchat_node": "正在回应...",              # 闲聊
    "ask_followup": "正在向你确认关键信息...",    # 阶段 3: 主动追问
    "judge_relevance": "正在判断问题类型...",     # 相关性判断
    "rag_retrieve": "正在检索知识库...",         # RAG 检索
    "rag_quality_eval": "正在评估检索质量...",   # 检索质量评估
    "query_corrector": "正在优化检索词...",      # 查询纠正
    "web_search": "正在联网搜索...",             # 联网搜索
    "generate_local": "正在生成回答...",         # 本地生成
    "generate_online": "正在生成回答...",        # 联网生成
    "multi_step_reason": "正在逐步推理...",      # 多步推理
    "combined_quality_check": "正在评估答案质量...",  # 合并质量评估
    "quality_fail": "正在生成提示...",           # 质量不合格
}


# 节点名 → 中文标签转换函数
def stage_label(node_name: str) -> str:
    """节点名 → 中文标签（白名单外节点兜底文案）。"""
    return STAGE_LABELS.get(node_name, f"执行: {node_name}")  # 命中取映射，否则兜底


# 每个节点下发哪些 output 字段（字段名与 graph/nodes.py 实际返回对齐）
TRACE_OUTPUT_FIELDS: dict[str, list[str]] = {
    "rewrite_query": ["rewritten_query"],                       # 改写后的查询
    "decompose_question": [                                     # 分类结果
        "is_chitchat",
        "needs_decomposition",
        "reasoning_steps",
        "safety_flag",                                          # 阶段 2: 高风险命中
        "safety_level",                                         # 阶段 2: 安全等级
        "safety_situation",                                     # 阶段 2: 设备状态
        "user_requests_human",                                  # 阶段 2: 要求人工
        "issue_profile",                                        # 阶段 3: 问题结构化画像
        "information_sufficient",                               # 阶段 3: 信息充分性
        "information_gaps",                                     # 阶段 3: 缺口清单
    ],
    "ask_followup": ["information_gaps", "judge_log"],          # 阶段 3: 追问依据
    "judge_relevance": ["is_relevant", "judge_log"],            # 相关性判断
    "rag_retrieve": ["retrieval_result", "avg_reranker_score"], # 检索结果
    "rag_quality_eval": ["rag_quality_pass", "judge_log"],      # 检索质量
    "query_corrector": ["rewritten_query", "correction_count"], # 纠正结果
    "web_search": ["web_search_result"],                        # 联网结果
    "combined_quality_check": [                                 # 合并质量评估
        "has_hallucination",                                    # 是否幻觉
        "answer_quality_pass",                                  # 质量是否通过
        "quality_check_error",                                  # 检查错误
        "judge_log",                                            # 判断记录
    ],
    "quality_fail": ["quality_warning"],                        # 质量告警
}
# chitchat_node / generate_local / generate_online / multi_step_reason
# 无白名单字段（正文走 token 流），仅显示名称+耗时。

_TRUNCATE_LIMIT = 200                                          # 长文本截断长度
_TRUNCATE_LIST_FIELDS = ("retrieval_result", "web_search_result", "reasoning_steps")  # 需逐项截断的列表字段


# 截断单个字符串
def truncate_text(text: str, limit: int = _TRUNCATE_LIMIT) -> str:
    """截断长文本，超限时末尾以省略号标记。非字符串原样返回。"""
    if not isinstance(text, str) or len(text) <= limit:  # 非字符串或未超限
        return text                                       # 原样返回
    return text[:limit] + "…"                             # 截断并追加省略号


# 截断列表内单个条目
def _truncate_item(item: object) -> object:
    """截断列表内条目：dict 截 content 字段，str 直接截断。"""
    if isinstance(item, dict):                            # 字典条目
        clipped = dict(item)                              # 拷贝避免改原对象
        if isinstance(clipped.get("content"), str):       # 有字符串 content
            clipped["content"] = truncate_text(clipped["content"])  # 截断其内容
        return clipped                                    # 返回剪辑后的字典
    if isinstance(item, str):                             # 字符串条目
        return truncate_text(item)                        # 直接截断
    return item                                           # 其它类型原样返回


# 按白名单提取节点 output
def extract_trace_output(node_name: str, output: dict | None) -> dict:
    """按白名单提取节点 output 的关键字段（构建 node_end 事件的 output）。

    - 白名单外的字段一律丢弃
    - judge_log 只取最后一条（当前节点的判断记录）
    - 列表字段（retrieval/web_search/reasoning_steps）内每条截断 200 字
    """
    if not output:                                        # 无输出
        return {}
    fields = TRACE_OUTPUT_FIELDS.get(node_name)           # 取该节点白名单字段
    if not fields:                                        # 不在白名单
        return {}
    result: dict = {}                                     # 结果字典
    for f in fields:                                      # 遍历白名单字段
        if f not in output:                               # 输出中无该字段
            continue                                      # 跳过
        v = output[f]                                     # 取值
        if f == "judge_log":                              # judge_log 特殊处理
            if isinstance(v, list) and v:                 # 是列表且有内容
                result[f] = v[-1]                         # 只取最后一条
        elif isinstance(v, list) and f in _TRUNCATE_LIST_FIELDS:  # 需逐项截断的列表
            result[f] = [_truncate_item(item) for item in v]      # 逐项截断
        else:                                             # 普通字段
            result[f] = v                                 # 原样保留
    return result                                         # 返回白名单结果


# 从流式 chunk 提取推理链增量
def extract_reasoning_content(chunk: object) -> str:
    """从流式 chunk 中提取 deepseek-reasoner 思维链增量，取不到返回空串。

    langchain-openai 把 reasoning_content 放在 additional_kwargs（AIMessageChunk）；
    兼容 dict 形态（含顶层 fallback）。调用方对空串跳过下发。
    """
    if hasattr(chunk, "additional_kwargs"):               # 对象带 additional_kwargs 属性
        kwargs = chunk.additional_kwargs or {}            # 取 kwargs 字典
        return kwargs.get("reasoning_content") or ""      # 从 kwargs 中取出推理内容
    if isinstance(chunk, dict):                           # dict 形态
        kwargs = chunk.get("additional_kwargs") or {}     # 取内层 kwargs
        return (                                          # 依次回退查找推理内容
            kwargs.get("reasoning_content")               # 内层
            or chunk.get("reasoning_content")             # 顶层
            or ""                                         # 兜底空串
        )
    return ""                                             # 其它类型返回空串
