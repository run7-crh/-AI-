# backend/app/api/health.py
import aiosqlite
from fastapi import APIRouter
from app.models.schemas import HealthResponse
from app.config import settings

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health():
    status = "ok"
    # P2-7: 轻量探测 SQLite + Chroma，依赖未就绪或探测失败时降级为 degraded。
    # 延迟导入避免与 main.py 循环导入；try/except 确保探测异常不阻塞响应。
    try:
        from app.main import get_store
        store = get_store()
        async with aiosqlite.connect(store.db_path) as db:
            await (await db.execute("SELECT 1")).fetchall()
    except Exception:
        status = "degraded"
    try:
        from app.api.index import get_indexer
        get_indexer().chroma_collection.count()
    except Exception:
        status = "degraded"
    return HealthResponse(
        status=status,
        model=settings.MODEL_FLASH,
        vector_db="chroma",
        embedding_model=settings.EMBEDDING_MODEL,
    )
