# backend/app/models/feedback.py
"""用户反馈系统的 Pydantic 模型。

第 2 阶段：用户对 Agent 回答打分，绑定到 query_log，用于后续优化。

字段约定：
- rating：'useful'(有帮助) / 'useless'(无帮助) / 'bug'(错误)
- useless_reason：仅 rating='useless' 时必填，4 类二级原因
- comment：可选文字补充
- upsert 语义：UNIQUE(query_log_id)，一条回答只能有一个反馈
"""
# 导入类型标注：Optional（可空）、Literal（限定取值）
from typing import Optional, Literal
# 导入 pydantic 的模型基类与字段校验工具
from pydantic import BaseModel, Field


# 定义反馈写入请求体模型
class FeedbackCreate(BaseModel):
    """PUT /api/feedback 请求体。"""

    query_log_id: str                            # 被反馈的查询日志 id
    rating: Literal['useful', 'useless', 'bug']  # 打分：有帮助/无帮助/错误
    useless_reason: Optional[Literal['irrelevant', 'hallucination', 'verbose', 'wrong_route']] = None  # 无用二级原因（可空）
    comment: Optional[str] = Field(None, max_length=1000)  # 文字补充（可选，最多 1000 字符）


# 定义反馈写入响应模型
class FeedbackResponse(BaseModel):
    """PUT /api/feedback 响应体。"""

    ok: bool = True                              # 是否成功
    feedback_id: str                             # 反馈 id


# 定义反馈统计响应模型
class FeedbackStats(BaseModel):
    """GET /api/feedback/stats 响应体。"""

    total: int                                   # 反馈总数
    useful_count: int                            # 有帮助数量
    useless_count: int                           # 无帮助数量
    bug_count: int                               # 错误数量
    useless_reason_breakdown: dict               # 无用原因分布 {irrelevant: N, hallucination: N, verbose: N, wrong_route: N}