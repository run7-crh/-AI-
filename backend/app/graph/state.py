# 导入类型标注工具：TypedDict（定义字典结构）、Optional（可选类型）、Annotated（附加元数据）
from typing import TypedDict, Optional, Annotated
# 从 Python 内置 operator 模块导入 add，用于 LangGraph 状态字段的叠加合并（列表追加）
from operator import add


# 定义 JudgeResult 类型：描述一次质量/真实性判断的结果结构
class JudgeResult(TypedDict):
    judge_type: str      # 判断类型（如 hallucination / quality）
    passed: bool         # 该判断是否通过（True=通过）
    raw_output: dict     # 评估器的原始输出，便于溯源与调试


# 定义 AgentState 类型：LangGraph 工作流流转的全局状态，对应 Dify 工作流的设计
class AgentState(TypedDict):
    """LangGraph 状态定义（对齐 Dify 工作流）。

    P0-2: 恢复 decompose/multi_step/chitchat 字段
    P1-1: 质量评估合并为一步：combined_quality_check
    """
    # 输入
    query: str                               # 用户原始提问
    conversation_id: str                     # 会话 ID，用于多轮对话上下文关联
    history: list[dict]                      # 历史对话记录，query rewrite 需参考以消解指代
    # 当前轮显式选择的临时附件；正文只存在本轮内存状态，不写入长期知识库。
    attachment_ids: list[str]
    attachment_context: Optional[str]
    attachment_evidence: list[dict]
    attachment_parse_status: Optional[str]

    # 中间产物
    rewritten_query: str                                # 改写后的查询（融合历史与纠错）
    is_chitchat: Optional[bool]                         # P1-5: 是否闲聊/问候，走快速通道
    intent: Optional[str]                               # 阶段 3：售后意图
    metadata_constraints: Optional[dict[str, str]]      # 阶段 3：检索元数据约束
    document_type_priority: Optional[list[str]]         # 阶段 3：文档类型优先级
    needs_decomposition: Optional[bool]                 # P0-2: 是否需要多步推理分解
    reasoning_steps: list[dict]                         # P0-2: 分解出的子问题列表
    is_relevant: Optional[bool]                         # 检索结果与问题是否相关
    retrieval_result: list[dict]                        # RAG 检索到的文档块（含来源与分数）
    avg_reranker_score: Optional[float]                 # P1-2: reranker 平均分，用于短路质量评估
    rag_quality_pass: Optional[bool]                    # RAG 检索质量是否通过
    # Structured web Evidence list; ``str`` remains accepted for old persisted
    # state and test fixtures during the migration.
    web_search_result: list[dict] | str                 # 联网检索结果（兼容旧状态为字符串）
    correction_count: int                               # CRAG: 检索失败后的纠正次数，上限 1 次防死循环

    # 质量评估（P1-1: 合并为一步）
    has_hallucination: Optional[bool]    # 幻觉检测结果（True=有幻觉）
    answer_quality_pass: Optional[bool]  # 答案质量评估结果
    quality_check_error: Optional[str]   # 评估器不可用时的错误标记，不等同于幻觉

    # 阶段 2：安全拦截与人工升级（decompose 一次 LLM 调用产出，生成节点消费）
    safety_flag: Optional[bool]          # 是否命中高风险情形
    safety_level: Optional[str]          # "high" / "none"
    safety_situation: Optional[str]      # "in_flight" / "landed" / "charging" / "unknown"
    user_requests_human: Optional[bool]  # 用户明确要求转人工
    # 可持久化计数（fault_progress 表）：同一故障两次"确认执行仍无效"后为 True，
    # 由 chat 层在图运行前写入；不是聊天轮数或 query_log 条数统计
    prior_troubleshoot_failed: Optional[bool]
    escalation_required: Optional[bool]  # 最终是否建议转人工（生成节点综合判定）

    # 输出
    final_answer: str                                    # 最终回答文本
    route_path: str                                      # 路由路径："local" / "online" / "chitchat" / "decomposition"
    quality_warning: Optional[str]                       # P1-3: 质量不合格时的警告文本（不覆盖 final_answer）

    # 评估日志（append 模式）
    judge_log: Annotated[list[JudgeResult], add]         # 用 add 叠加，形成评估日志列表
