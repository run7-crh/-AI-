# backend/app/models/feedback.py
"""用户反馈系统的 Pydantic 模型。

第 2 阶段：用户对 Agent 回答打分，绑定到 query_log，用于后续优化。

字段约定：
- rating：'useful'(有帮助) / 'useless'(无帮助) / 'bug'(错误)
- useless_reason：仅 rating='useless' 时必填，4 类二级原因
- comment：可选文字补充
- upsert 语义：UNIQUE(query_log_id)，一条回答只能有一个反馈
"""
from typing import Optional, Literal
from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    """PUT /api/feedback 请求体。"""

    query_log_id: str
    rating: Literal['useful', 'useless', 'bug']
    useless_reason: Optional[Literal['irrelevant', 'hallucination', 'verbose', 'wrong_route']] = None
    comment: Optional[str] = Field(None, max_length=1000)


class FeedbackResponse(BaseModel):
    """PUT /api/feedback 响应体。"""

    ok: bool = True
    feedback_id: str


class FeedbackStats(BaseModel):
    """GET /api/feedback/stats 响应体。"""

    total: int
    useful_count: int
    useless_count: int
    bug_count: int
    useless_reason_breakdown: dict  # {irrelevant: N, hallucination: N, verbose: N, wrong_route: N}
