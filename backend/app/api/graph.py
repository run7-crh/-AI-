# backend/app/api/graph.py
"""知识图谱只读 API：读 kg.json 原样返回，支持 ETag/304。"""
import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(prefix="/api/graph", tags=["graph"])
logger = logging.getLogger(__name__)


@router.get("")
async def get_graph(request: Request):
    path = Path(settings.KG_JSON_PATH)
    if not path.exists():
        raise HTTPException(status_code=404, detail="knowledge graph not built")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.error("kg.json 解析失败", exc_info=True)
        raise HTTPException(status_code=500, detail="knowledge graph data corrupted")

    # ETag 取 built_at 哈希：重建后指纹变化，客户端缓存自动失效
    etag = f'W/"{hashlib.md5(str(data.get("built_at", "")).encode()).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(data, headers={"ETag": etag})
