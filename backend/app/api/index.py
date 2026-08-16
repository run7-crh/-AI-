# backend/app/api/index.py
import logging

from fastapi import APIRouter, HTTPException, Request
from app.models.schemas import IndexRebuildResponse
from app.rag.indexer import Indexer
from app.rag.graph_builder import build_knowledge_graph
from app.extensions import limiter

router = APIRouter(prefix="/api/index", tags=["index"])

logger = logging.getLogger(__name__)

_indexer: Indexer = None


def set_indexer(indexer: Indexer) -> None:
    global _indexer
    _indexer = indexer


def get_indexer() -> Indexer:
    if _indexer is None:
        raise RuntimeError("Indexer not initialized")
    return _indexer


@router.post("/rebuild", response_model=IndexRebuildResponse)
@limiter.limit("1/minute")
async def rebuild_index(request: Request):
    # 直接调用 get_indexer()，不使用 Depends，便于测试 monkeypatch 生效
    indexer = get_indexer()
    try:
        indexer.build()
        doc_count = indexer.chroma_collection.count()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"索引重建失败: {e}")

    # 索引成功后构建知识图谱；失败不阻塞索引，仅标记 graph_built=False
    graph_built = True
    try:
        await build_knowledge_graph()
    except Exception:
        logger.warning("知识图谱构建失败（不影响索引）", exc_info=True)
        graph_built = False

    return IndexRebuildResponse(success=True, doc_count=doc_count, graph_built=graph_built)
