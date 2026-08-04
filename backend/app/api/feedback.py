# backend/app/api/feedback.py
"""用户反馈接口。

- PUT /api/feedback：upsert 反馈（幂等）
- GET /api/feedback/stats：统计反馈数据
"""
import logging
from fastapi import APIRouter, Depends, HTTPException

from app.models.feedback import FeedbackCreate, FeedbackResponse, FeedbackStats
from app.services.feedback_service import FeedbackStore

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)

_store: FeedbackStore = None


def set_store(store: FeedbackStore) -> None:
    global _store
    _store = store


def get_store() -> FeedbackStore:
    if _store is None:
        raise RuntimeError("FeedbackStore not initialized")
    return _store


@router.put("", response_model=FeedbackResponse)
async def put_feedback(body: FeedbackCreate, store: FeedbackStore = Depends(get_store)):
    """upsert 用户反馈。

    - rating='useless' 时 useless_reason 必填（service 层校验，422）
    - query_log_id 不存在返回 404（外键校验）
    - 同一 query_log_id 多次 PUT 走 ON CONFLICT 更新（幂等）
    """
    try:
        feedback_id = await store.upsert(body)
    except ValueError as e:
        msg = str(e)
        if "useless_reason" in msg:
            raise HTTPException(status_code=422, detail=msg)
        if "query_log_id 不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    return FeedbackResponse(ok=True, feedback_id=feedback_id)


@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats(store: FeedbackStore = Depends(get_store)):
    """统计反馈数据（总数 + 按 rating 分组 + useless_reason 分布）。"""
    stats = await store.get_stats()
    return FeedbackStats(**stats)
