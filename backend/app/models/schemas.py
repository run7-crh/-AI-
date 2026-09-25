# backend/app/models/schemas.py
# 导入 pydantic 的模型基类与字段校验工具
from pydantic import BaseModel, Field, model_validator
# 导入 datetime，用于时间字段
from datetime import datetime
# 导入类型标注：Optional（可空）、Literal（限定取值）
from typing import Optional, Literal

# 认证请求与公开用户响应模型统一从 auth 模块导出，兼容 schema 聚合导入。
from app.models.auth import Credentials, UserPublic


# 定义聊天请求体模型
class ChatRequest(BaseModel):
    conversation_id: str                       # 会话 ID
    # Empty text is valid only when the current turn explicitly includes a
    # ready attachment; the validator below preserves the legacy requirement
    # for ordinary text-only requests.
    message: str = Field(..., min_length=0, max_length=2000)
    # 第 1 阶段：朋友测试时区分谁问的（如 'A'/'B'/'C'），用于 query_log 诊断
    user_label: Optional[str] = Field(None, max_length=50)  # 提问者标识（可选，最多 50 字符）
    # 当前轮明确使用的临时附件；不传则保持原有聊天行为。
    attachment_ids: Optional[list[str]] = Field(None, max_length=10)

    @model_validator(mode="after")
    def require_message_or_attachment(self):
        if not self.message.strip() and not self.attachment_ids:
            raise ValueError("message_or_attachment_required")
        return self


# 定义创建会话请求体模型
class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=100)  # 会话标题（可选，最多 100 字符）


# 定义更新会话请求体模型
class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)  # 新标题（1~100 字符，必填）


# 定义会话列表项响应模型
class ConversationResponse(BaseModel):
    id: str                                    # 会话 ID
    title: str                                 # 会话标题
    created_at: datetime                       # 创建时间
    updated_at: datetime                       # 更新时间
    message_count: int                         # 消息条数


# 定义单条消息响应模型
class MessageAttachmentSummary(BaseModel):
    """Non-content attachment metadata linked to a historical message."""
    id: str
    attachment_id: Optional[str] = None
    original_name: str
    extension: str
    declared_mime: Optional[str] = None
    detected_mime: Optional[str] = None
    size_bytes: int
    status: str
    extraction_status: str
    extracted_chars: Optional[int] = None
    extraction_error: Optional[str] = None
    scan_status: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class MessageResponse(BaseModel):
    id: str                                    # 消息 ID
    role: Literal["user", "assistant"]         # 角色：用户或助手
    content: str                               # 消息内容
    route_path: Optional[str] = None           # 本次路由路径（可选）
    sources: Optional[list[dict]] = None       # 引用来源列表（可选）
    judge_log: Optional[list[dict]] = None     # 判断过程日志（可选）
    quality_warning: Optional[str] = None      # 质量告警信息（可选）
    query_log_id: Optional[str] = None         # 关联的查询日志 ID（可选）
    safety_flag: Optional[bool] = None         # 后端安全判断结果（可选）
    safety_level: Optional[str] = None         # 安全等级（可选）
    safety_situation: Optional[str] = None     # 设备状态（可选）
    escalation_required: Optional[bool] = None  # 是否建议人工升级（可选）
    intent: Optional[str] = None               # 售后意图（可选）
    metadata_constraints: Optional[dict] = None # 检索元数据约束（可选）
    document_type_priority: Optional[list[str]] = None  # 文档类型优先级（可选）
    attachments: Optional[list[MessageAttachmentSummary]] = None  # 用户附件摘要（不含正文）
    created_at: datetime                       # 创建时间


class AttachmentResponse(BaseModel):
    """Public attachment metadata; never includes storage paths or text."""
    id: str
    attachment_id: str
    original_name: str
    extension: str
    declared_mime: Optional[str] = None
    detected_mime: Optional[str] = None
    size_bytes: int
    sha256: str
    status: str
    extraction_status: str
    extracted_chars: Optional[int] = None
    extraction_error: Optional[str] = None
    extraction_error_code: Optional[str] = None
    extraction_summary: Optional[str] = None
    scan_status: str
    created_at: datetime
    expires_at: datetime
    deleted_at: Optional[datetime] = None


# 定义会话详情响应模型（继承列表项，追加消息）
class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]            # 消息列表


# 定义索引重建响应模型
class IndexRebuildResponse(BaseModel):
    success: bool                              # 是否成功
    # 保留 doc_count 兼容旧前端；它现在表示去重后的 Markdown 文档数。
    doc_count: int                             # 去重后的文档数
    vector_count: int = 0                      # 向量条数
    # 知识图谱构建结果（构建失败不阻塞索引，仅置 False，前端可提示重建）
    graph_built: bool = True                   # 知识图谱是否构建成功


# 定义健康检查响应模型
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]          # 整体状态：正常或降级
    model: str                                 # 大模型是否可用
    vector_db: str                             # 向量库是否可用
    embedding_model: str                       # embedding 模型是否可用
