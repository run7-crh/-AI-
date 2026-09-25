# backend/app/api/index.py
# 导入日志模块
import logging
# 导入 asyncio，用于异步锁与线程池
import asyncio

# 导入 FastAPI 路由、异常、请求类
from fastapi import APIRouter, HTTPException, Request, Depends
# 导入索引重建响应模型
from app.models.schemas import IndexRebuildResponse
# 导入索引构建器
from app.rag.indexer import Indexer
# 导入知识图谱构建函数
from app.rag.graph_builder import build_knowledge_graph
# 导入限速器
from app.extensions import limiter
from app.api.dependencies import require_admin

# 创建索引管理路由，前缀 /api/index
router = APIRouter(prefix="/api/index", tags=["index"])

# 获取当前模块日志器
logger = logging.getLogger(__name__)

_indexer: Indexer = None           # 全局索引器实例（由 main 注入）
_rebuild_lock = asyncio.Lock()     # 重建互斥锁，防止并发重建


# 注入索引器实例
def set_indexer(indexer: Indexer) -> None:
    global _indexer
    _indexer = indexer             # 保存索引器


# 获取当前索引器实例
def get_indexer() -> Indexer:
    if _indexer is None:           # 尚未初始化
        raise RuntimeError("Indexer not initialized")  # 抛错
    return _indexer                # 返回索引器


# 定义索引重建接口
@router.post("/rebuild", response_model=IndexRebuildResponse)
@limiter.limit("1/minute")          # 每分钟限 1 次，防止滥用
async def rebuild_index(request: Request, _admin=Depends(require_admin)):
    # 直接调用 get_indexer()，不使用 Depends，便于测试 monkeypatch 生效
    indexer = get_indexer()        # 取索引器
    if _rebuild_lock.locked():     # 已在重建中
        raise HTTPException(status_code=409, detail="索引正在重建，请稍后再试")  # 并发冲突
    try:                           # 尝试执行重建
        async with _rebuild_lock:  # 持有互斥锁
            # Embedding and vector writes are synchronous and can take many
            # seconds; keep the FastAPI event loop free for other requests.
            await asyncio.to_thread(indexer.build)  # 放线程池执行避免阻塞事件循环
            # Indexer publishes a new collection only after it is complete.
            # Rebuild the graph binding so future requests use that snapshot;
            # in-flight requests retain their existing retriever safely.
            from app.api import chat as chat_api    # 延迟导入聊天模块
            from app.graph.builder import build_graph  # 延迟导入图构建器

            chat_api.set_graph(build_graph(indexer.get_retriever()))  # 用新检索器重建工作流绑定
            vector_count = indexer.chroma_collection.count()  # 统计向量数
            # Chroma count is a chunk/vector count, not a Markdown document
            # count.  Prefer stable document_id metadata and keep a fallback
            # for older collections/mocks without readable metadata.
            doc_count = vector_count               # 默认文档数取向量数兜底
            try:                                   # 尝试从元数据推算真实文档数
                records = indexer.chroma_collection.get(include=["metadatas"])  # 取元数据
                metadatas = records.get("metadatas", []) if isinstance(records, dict) else []  # 提取元数据列表
                document_ids = {                   # 收集去重的文档 id 集合
                    str(meta.get("document_id") or meta.get("file_name"))
                    for meta in metadatas
                    if isinstance(meta, dict) and (meta.get("document_id") or meta.get("file_name"))
                }
                if document_ids:                   # 拿到有效文档 id
                    doc_count = len(document_ids)  # 文档数即 id 去重数量
            except Exception:                      # 读取元数据失败
                logger.warning("无法读取索引文档元数据，doc_count 回退为 vector_count", exc_info=True)  # 记录告警
    except Exception as e:                         # 重建失败
        raise HTTPException(status_code=500, detail=f"索引重建失败: {e}")  # 500 错误

    # 索引成功后构建知识图谱；失败不阻塞索引，仅标记 graph_built=False
    graph_built = True                             # 默认标记构建成功
    try:                                           # 尝试构建图谱
        await build_knowledge_graph()              # 执行图谱构建
    except Exception:                              # 构建失败
        logger.warning("知识图谱构建失败（不影响索引）", exc_info=True)  # 记录告警
        graph_built = False                        # 标记失败

    return IndexRebuildResponse(                   # 返回重建结果
        success=True,                              # 成功标记
        doc_count=doc_count,                       # 文档数
        vector_count=vector_count,                 # 向量数
        graph_built=graph_built,                   # 图谱是否构建成功
    )
