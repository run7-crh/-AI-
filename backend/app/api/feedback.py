# backend/app/api/feedback.py
"""用户反馈接口。

- PUT /api/feedback：upsert 反馈（幂等）
- GET /api/feedback/stats：统计反馈数据
"""
# 导入日志模块
import logging
# 导入 FastAPI 路由、依赖注入、异常类
from fastapi import APIRouter, Depends, HTTPException

# 导入反馈相关数据模型
from app.models.feedback import FeedbackCreate, FeedbackResponse, FeedbackStats
# 导入反馈存储服务
from app.services.feedback_service import FeedbackStore
from app.api.dependencies import get_current_user, require_admin

# 创建反馈路由，前缀 /api/feedback
router = APIRouter(prefix="/api/feedback", tags=["feedback"])
# 获取当前模块日志器
logger = logging.getLogger(__name__)

_store: FeedbackStore = None          # 全局反馈存储实例（由 main 注入）


# 注入反馈存储实例
def set_store(store: FeedbackStore) -> None:
    global _store
    _store = store                    # 保存存储实例


# 获取当前反馈存储实例
def get_store() -> FeedbackStore:
    if _store is None:                # 尚未初始化
        raise RuntimeError("FeedbackStore not initialized")  # 抛错
    return _store                     # 返回存储实例


# 定义提交反馈接口
@router.put("", response_model=FeedbackResponse)
async def put_feedback(body: FeedbackCreate, store: FeedbackStore = Depends(get_store), user=Depends(get_current_user)):
    """upsert 用户反馈。

    - rating='useless' 时 useless_reason 必填（service 层校验，422）
    - query_log_id 不存在返回 404（外键校验）
    - 同一 query_log_id 多次 PUT 走 ON CONFLICT 更新（幂等）
    """
    try:                              # 尝试写入反馈
        feedback_id = await store.upsert(body, user.id)  # 调用存储 upsert
    except ValueError as e:           # 业务校验错误
        msg = str(e)                  # 取错误信息
        if "useless_reason" in msg:   # 缺无用原因
            raise HTTPException(status_code=422, detail=msg)  # 422 参数错误
        if "query_log_id 不存在" in msg:  # 日志记录不存在
            raise HTTPException(status_code=404, detail=msg)  # 404
        raise HTTPException(status_code=422, detail=msg)      # 其它参数错误 422

    return FeedbackResponse(ok=True, feedback_id=feedback_id)  # 返回成功与反馈 id


# 定义反馈统计接口
@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats(store: FeedbackStore = Depends(get_store), _admin=Depends(require_admin)):
    """统计反馈数据（总数 + 按 rating 分组 + useless_reason 分布）。"""
    stats = await store.get_stats()   # 取统计数据
    return FeedbackStats(**stats)     # 映射为响应模型返回
