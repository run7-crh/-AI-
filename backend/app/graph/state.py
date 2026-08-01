from typing import TypedDict, Optional, Annotated
from operator import add


class JudgeResult(TypedDict):
    judge_type: str
    passed: bool
    raw_output: dict


class AgentState(TypedDict):
    """LangGraph 状态定义（对齐 Dify 工作流）。

    P0-2: 恢复 decompose/multi_step/chitchat 字段
    P1-1: 质量评估合并为一步：combined_quality_check
    """
    # 输入
    query: str
    conversation_id: str
    history: list[dict]

    # 中间产物
    rewritten_query: str
    is_chitchat: Optional[bool]  # P1-5: 闲聊/问候快速通道
    needs_decomposition: Optional[bool]  # P0-2: 是否需要多步推理
    reasoning_steps: list[dict]  # P0-2: 分解的子问题
    is_relevant: Optional[bool]
    retrieval_result: list[dict]
    avg_reranker_score: Optional[float]  # P1-2: reranker 平均分用于短路质量评估
    rag_quality_pass: Optional[bool]
    web_search_result: str
    correction_count: int  # CRAG: 检索失败后的纠正次数，上限 1 次防死循环

    # 质量评估（P1-1: 合并为一步）
    has_hallucination: Optional[bool]  # 幻觉检测结果（True=有幻觉）
    answer_quality_pass: Optional[bool]  # 答案质量评估结果

    # 输出
    final_answer: str
    route_path: str  # "local" / "online" / "chitchat" / "decomposition"
    quality_warning: Optional[str]  # P1-3: 质量不合格时的警告文本（不覆盖 final_answer）

    # 评估日志（append 模式）
    judge_log: Annotated[list[JudgeResult], add]
