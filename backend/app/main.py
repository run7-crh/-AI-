# backend/app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import health, conversations
from app.api.errors import register_error_handlers
from app.services.conversation_store import ConversationStore
from app.config import settings

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
register_error_handlers(app)
