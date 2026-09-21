# backend/app/api/graph.py
"""知识图谱只读 API：读 kg.json 原样返回，支持 ETag/304。"""
# 导入 hashlib，用于生成 ETag 哈希
import hashlib
# 导入 json，用于解析 kg.json
import json
# 导入日志模块
import logging
# 导入 Path，用于路径操作
from pathlib import Path

# 导入 FastAPI 路由、异常、请求、响应类
from fastapi import APIRouter, Depends, HTTPException, Request, Response
# 导入 JSON 响应类
from fastapi.responses import JSONResponse

# 导入全局配置
from app.config import settings
from app.api.dependencies import get_current_user

# 创建图谱路由，前缀 /api/graph
router = APIRouter(prefix="/api/graph", tags=["graph"])
# 获取当前模块日志器
logger = logging.getLogger(__name__)


# 定义获取知识图谱接口
@router.get("")
async def get_graph(request: Request, _user=Depends(get_current_user)):
    path = Path(settings.KG_JSON_PATH)             # 图谱产物文件路径
    if not path.exists():                          # 文件不存在
        raise HTTPException(status_code=404, detail="knowledge graph not built")  # 404
    try:                                           # 尝试解析
        data = json.loads(path.read_text(encoding="utf-8"))  # 读取并解析 JSON
    except Exception:                              # 解析失败
        logger.error("kg.json 解析失败", exc_info=True)  # 记录错误
        raise HTTPException(status_code=500, detail="knowledge graph data corrupted")  # 500

    # ETag 取 built_at 哈希：重建后指纹变化，客户端缓存自动失效
    etag = f'W/"{hashlib.md5(str(data.get("built_at", "")).encode()).hexdigest()}"'  # 计算资源指纹
    if request.headers.get("if-none-match") == etag:  # 客户端携带的指纹一致
        return Response(status_code=304, headers={"ETag": etag})  # 返回 304 未修改
    return JSONResponse(data, headers={"ETag": etag})  # 返回图谱数据并附带 ETag
