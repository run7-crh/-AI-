# backend/app/api/index.py
from fastapi import APIRouter, HTTPException
from app.models.schemas import IndexRebuildResponse
from app.rag.indexer import Indexer

router = APIRouter(prefix="/api/index", tags=["index"])

_indexer: Indexer = None


def set_indexer(indexer: Indexer) -> None:
    global _indexer
    _indexer = indexer


def get_indexer() -> Indexer:
    if _indexer is None:
        raise RuntimeError("Indexer not initialized")
    return _indexer


@router.post("/rebuild", response_model=IndexRebuildResponse)
async def rebuild_index():
    # 直接调用 get_indexer()，不使用 Depends，便于测试 monkeypatch 生效
    indexer = get_indexer()
    try:
        indexer.build()
        doc_count = indexer.chroma_collection.count()
        return IndexRebuildResponse(success=True, doc_count=doc_count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"索引重建失败: {e}")
