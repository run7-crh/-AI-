from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal


class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(..., min_length=1, max_length=2000)
    # 第 1 阶段：朋友测试时区分谁问的（如 'A'/'B'/'C'），用于 query_log 诊断
    user_label: Optional[str] = Field(None, max_length=50)


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=100)


class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class MessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    route_path: Optional[str] = None
    sources: Optional[list[dict]] = None
    judge_log: Optional[list[dict]] = None
    created_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]


class IndexRebuildResponse(BaseModel):
    success: bool
    doc_count: int
    # 知识图谱构建结果（构建失败不阻塞索引，仅置 False，前端可提示重建）
    graph_built: bool = True


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    model: str
    vector_db: str
    embedding_model: str
