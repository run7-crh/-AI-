# backend/app/api/health.py
# 导入 aiosqlite，用于异步探测 SQLite 连通性
import aiosqlite
# 导入 FastAPI 路由类
from fastapi import APIRouter
# 导入健康检查响应模型
from app.models.schemas import HealthResponse
# 导入全局配置
from app.config import settings

# 创建健康检查路由，前缀 /api/health
router = APIRouter(prefix="/api/health", tags=["health"])


# 定义健康检查接口
@router.get("", response_model=HealthResponse)
async def health():
    status = "ok"                                  # 初始状态为正常
    # P2-7: 轻量探测 SQLite + Chroma，依赖未就绪或探测失败时降级为 degraded。
    # 延迟导入避免与 main.py 循环导入；try/except 确保探测异常不阻塞响应。
    try:                                           # 尝试探测 SQLite
        from app.main import get_store             # 延迟导入避免循环依赖
        store = get_store()                        # 获取存储实例
        async with aiosqlite.connect(store.db_path) as db:  # 连接数据库
            await (await db.execute("SELECT 1")).fetchall()  # 探测连通性
    except Exception:                              # 探测失败
        status = "degraded"                        # 降级
    try:                                           # 尝试探测 Chroma
        from app.api.index import get_indexer      # 延迟导入避免循环依赖
        get_indexer().chroma_collection.count()    # 探测向量库
    except Exception:                              # 探测失败
        status = "degraded"                        # 降级
    return HealthResponse(                         # 返回健康状态
        status=status,                             # 整体状态
        model=settings.MODEL_FLASH,                # 大模型配置名
        vector_db="chroma",                        # 向量库类型
        embedding_model=settings.EMBEDDING_MODEL,  # embedding 模型名
    )
