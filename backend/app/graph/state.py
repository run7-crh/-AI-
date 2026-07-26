from typing import TypedDict, Optional, Annotated
from operator import add


class JudgeResult(TypedDict):
    judge_type: str
    passed: bool
    raw_output: dict


class AgentState(TypedDict):
    # 输入
    query: str
    conversation_id: str
    history: list[dict]

    # 中间产物
    rewritten_query: str
    needs_decomposition: bool
    reasoning_steps: list[dict]
    reasoning_result: str

    is_relevant: Optional[bool]
    retrieval_result: list[dict]
    rag_quality_pass: Optional[bool]
    web_search_result: str
    local_answer: str
    online_answer: str
    hallucination_flag: Optional[bool]
    answer_quality_pass: Optional[bool]

    # 输出
    final_answer: str
    route_path: str

    # 评估日志（append 模式）
    judge_log: Annotated[list[JudgeResult], add]
