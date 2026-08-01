# backend/app/main.py
import os
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api import health, conversations
from app.api import index as index_api
from app.api.errors import register_error_handlers
from app.extensions import limiter
from app.services.conversation_store import ConversationStore
from app.config import settings

# 日志文件路径（uvicorn 启动后会覆盖 basicConfig，所以在 lifespan 中再配置一次）
_log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "app.log")

logger = logging.getLogger(__name__)

_store: ConversationStore = None


def _setup_file_logging() -> None:
    """在 lifespan 中调用，确保覆盖 uvicorn 的 dictConfig。

    P1-11: 用 RotatingFileHandler 替代 FileHandler，避免日志文件无限增长。
    配置：10MB 单文件上限，保留 5 份历史，UTF-8 编码。
    uvicorn 启动时用 dictConfig 配置日志会清除 basicConfig 的 handler，
    在 lifespan 中重新给 root logger 添加 RotatingFileHandler 确保错误日志落盘。
    """
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    # P1-11: RotatingFileHandler 实现日志轮转（10MB × 5 份 = 最多 50MB）
    fh = RotatingFileHandler(
        _log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.INFO)

    # root logger 添加 RotatingFileHandler
    root = logging.getLogger()
    root.addHandler(fh)

    # app.* logger 确保传播到 root（不单独设置 propagate=False）
    for name in ("app", "app.api", "app.api.chat", "app.graph", "app.graph.tools", "app.graph.nodes"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)


def get_store() -> ConversationStore:
    if _store is None:
        raise RuntimeError("Store not initialized")
    return _store


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store
    # 在 lifespan 中配置文件日志，覆盖 uvicorn 的 dictConfig
    _setup_file_logging()
    logger.info("=== 应用启动 ===")

    db_path = os.environ.get("TEST_SQLITE_PATH", settings.SQLITE_PATH)
    _store = ConversationStore(db_path)
    await _store.init()
    conversations.set_store(_store)

    # P0-3: Reranker 预热（GPU 加速，避免首次请求卡顿 2GB 模型加载）
    try:
        from app.rag.retriever import get_cross_encoder
        get_cross_encoder(settings.RERANKER_MODEL)
        logger.info("Reranker 预热完成")
    except Exception as e:
        logger.warning(f"Reranker 预热失败: {e}")

    # 初始化 graph（失败降级到 None，不阻塞应用启动；chat 路由调用时再报错）
    try:
        from app.rag.indexer import Indexer
        from app.graph.builder import build_graph
        from app.api import chat as chat_module

        _indexer = Indexer(
            data_dir=settings.KB_DATA_DIR,
            persist_dir=settings.CHROMA_PERSIST_DIR,
        )
        _indexer.load_or_build()
        _graph = build_graph(_indexer.get_retriever())
        chat_module.set_graph(_graph)
        index_api.set_indexer(_indexer)
        logger.info("Graph 初始化成功")
    except Exception as e:
        logger.warning(f"Graph 初始化失败（开发期可继续）: {e}")

    yield
    logger.info("=== 应用关闭 ===")


app = FastAPI(title="学AI必备助手 API", version="1.0.0", lifespan=lifespan)
# P1-10: 注册 slowapi 限速器和异常处理器
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(conversations.router)

# chat 模块依赖 get_store，必须在 get_store 定义后导入
from app.api import chat  # noqa: E402

app.include_router(chat.router)
app.include_router(index_api.router)
register_error_handlers(app)
