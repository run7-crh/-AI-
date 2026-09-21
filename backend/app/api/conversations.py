# backend/app/api/conversations.py
from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationDetail,
)
from app.services.conversation_store import ConversationStore
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

_store: ConversationStore = None


def set_store(store: ConversationStore) -> None:
    global _store
    _store = store


def get_store() -> ConversationStore:
    if _store is None:
        raise RuntimeError("Store not initialized")
    return _store


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    store: ConversationStore = Depends(get_store),
    _user=Depends(get_current_user),
):
    conv_id = await store.create_conversation(title=body.title)
    conv = await store.get_conversation(conv_id)
    return ConversationResponse(**{k: v for k, v in conv.items() if k != "messages"})


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    store: ConversationStore = Depends(get_store),
    _user=Depends(get_current_user),
):
    convs = await store.list_conversations()
    return [ConversationResponse(**conv) for conv in convs]


@router.get("/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: str,
    store: ConversationStore = Depends(get_store),
    _user=Depends(get_current_user),
):
    conv = await store.get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


@router.patch("/{conv_id}", response_model=ConversationResponse)
async def update_conversation(
    conv_id: str,
    body: ConversationUpdate,
    store: ConversationStore = Depends(get_store),
    _user=Depends(get_current_user),
):
    ok = await store.update_conversation_title(conv_id, body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    conv = await store.get_conversation(conv_id)
    return ConversationResponse(**{k: v for k, v in conv.items() if k != "messages"})


@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: str,
    store: ConversationStore = Depends(get_store),
    _user=Depends(get_current_user),
):
    ok = await store.delete_conversation(conv_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True}
