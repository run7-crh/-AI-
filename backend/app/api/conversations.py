# backend/app/api/conversations.py
# 导入 FastAPI 路由、依赖注入、异常类
from fastapi import APIRouter, Depends, HTTPException
# 导入会话相关数据模型
from app.models.schemas import (
    ConversationCreate,   # 创建请求体
    ConversationUpdate,   # 更新请求体
    ConversationResponse, # 列表项响应
    ConversationDetail,   # 详情响应（含消息）
)
# 导入会话存储服务
from app.services.conversation_store import ConversationStore
from app.api.dependencies import get_current_user

# 创建会话路由，前缀 /api/conversations
router = APIRouter(prefix="/api/conversations", tags=["conversations"])

_store: ConversationStore = None      # 全局会话存储实例（由 main 注入）


# 注入会话存储实例
def set_store(store: ConversationStore) -> None:
    global _store
    _store = store                    # 保存存储实例


# 获取当前会话存储实例
def get_store() -> ConversationStore:
    if _store is None:                # 尚未初始化
        raise RuntimeError("Store not initialized")  # 抛错
    return _store                     # 返回存储实例


# 定义创建会话接口
@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    body: ConversationCreate,
    store: ConversationStore = Depends(get_store),
    user=Depends(get_current_user),
):
    conv_id = await store.create_conversation(title=body.title, user_id=user.id)  # 创建会话
    conv = await store.get_conversation(conv_id, user.id)   # 回查新会话
    return ConversationResponse(**{k: v for k, v in conv.items() if k != "messages"})  # 剔除消息字段映射返回


# 定义会话列表接口
@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    store: ConversationStore = Depends(get_store),
    user=Depends(get_current_user),
):
    convs = await store.list_conversations(user.id)       # 取当前用户会话
    return [ConversationResponse(**conv) for conv in convs]  # 逐个映射返回


# 定义会话详情接口
@router.get("/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: str,
    store: ConversationStore = Depends(get_store),
    user=Depends(get_current_user),
):
    conv = await store.get_conversation(conv_id, user.id)   # 查会话（含消息）
    if not conv:                                   # 不存在
        raise HTTPException(status_code=404, detail="会话不存在")  # 404
    return conv                                    # 返回详情


# 定义更新会话标题接口
@router.patch("/{conv_id}", response_model=ConversationResponse)
async def update_conversation(
    conv_id: str,
    body: ConversationUpdate,
    store: ConversationStore = Depends(get_store),
    user=Depends(get_current_user),
):
    ok = await store.update_conversation_title(conv_id, body.title, user.id)  # 更新标题
    if not ok:                                    # 无更新（会话不存在）
        raise HTTPException(status_code=404, detail="会话不存在")  # 404
    conv = await store.get_conversation(conv_id, user.id)   # 回查会话
    return ConversationResponse(**{k: v for k, v in conv.items() if k != "messages"})  # 剔除消息字段返回


# 定义删除会话接口
@router.delete("/{conv_id}")
async def delete_conversation(
    conv_id: str,
    store: ConversationStore = Depends(get_store),
    user=Depends(get_current_user),
):
    if await store.get_conversation(conv_id, user.id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    # Remove private attachment bytes before the FK cascade removes metadata.
    try:
        from app.api.attachments import get_store as get_attachment_store
        attachment_store = get_attachment_store()
        if attachment_store is not None:
            await attachment_store.delete_conversation_attachments(conv_id)
    except RuntimeError:
        attachment_store = None
    ok = await store.delete_conversation(conv_id, user.id)  # 删除会话（连带消息与日志）
    if not ok:                                     # 无删除（不存在）
        raise HTTPException(status_code=404, detail="会话不存在")  # 404
    return {"success": True}                       # 返回成功
