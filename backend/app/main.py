# backend/app/main.py
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import health, conversations
from app.api.errors import register_error_handlers
from app.services.conversation_store import ConversationStore
from app.config import settings

logger = logging.getLogger(__name__)

_store: ConversationStore = None


def get_store() -> ConversationStore:
    if _store is None:
        raise RuntimeError("Store not initialized")
    return _store


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store
    db_path = os.environ.get("TEST_SQLITE_PATH", settings.SQLITE_PATH)
    _store = ConversationStore(db_path)
    await _store.init()
    conversations.set_store(_store)

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
        logger.info("Graph 初始化成功")
    except Exception as e:
        logger.warning(f"Graph 初始化失败（开发期可继续）: {e}")

    yield


app = FastAPI(title="学AI必备助手 API", version="1.0.0", lifespan=lifespan)
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
register_error_handlers(app)
