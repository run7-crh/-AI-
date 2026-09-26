# backend/app/main.py
# 导入 os，用于路径与环境变量操作
import os
# 导入日志模块
import logging
# 导入按大小轮转的日志处理器，避免日志文件无限增长
from logging.handlers import RotatingFileHandler
# 导入异步上下文管理器装饰器，用于应用生命周期
from contextlib import asynccontextmanager
# 导入 FastAPI 应用类与请求对象
from fastapi import FastAPI, Request
# 导入 CORS 中间件
from fastapi.middleware.cors import CORSMiddleware
# 导入 JSON 响应类
from fastapi.responses import JSONResponse
# 导入 slowapi 的限流超限默认处理器
from slowapi import _rate_limit_exceeded_handler
# 导入限流超限异常
from slowapi.errors import RateLimitExceeded
# 导入健康检查与会话路由（app.api 包内模块）
from app.api import health, conversations, attachments, auth, admin
from app.api.dependencies import set_auth_store
# 导入工单路由（售后工单闭环）
from app.api import tickets
from app.api import admin_tickets
# 导入索引管理路由（起别名避免与内置 index 冲突）
from app.api import index as index_api
# 导入反馈路由
from app.api import feedback
# 导入错误处理器注册函数
from app.api.errors import register_error_handlers
# 导入全局限速器
from app.extensions import limiter
# 导入会话存储服务
from app.services.conversation_store import ConversationStore
# 导入查询日志存储服务
from app.services.query_log_service import QueryLogStore
# 导入反馈存储服务
from app.services.feedback_service import FeedbackStore
# 导入排查失败计数存储服务（阶段 2: 人工升级建议）
from app.services.fault_progress_service import FaultProgressStore
from app.services.attachment_store import AttachmentStore, LocalAttachmentStorage
from app.services.auth_store import AuthStore
from app.services.ticket_store import TicketStore
from app.services.ticket_service import TicketService
# 导入全局配置
from app.config import settings

# 日志文件路径（uvicorn 启动后会覆盖 basicConfig，所以在 lifespan 中再配置一次）
_log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "logs")  # 日志目录：backend/data/logs
os.makedirs(_log_dir, exist_ok=True)           # 确保日志目录存在
_log_file = os.path.join(_log_dir, "app.log")  # 日志文件完整路径

# 获取当前模块日志器
logger = logging.getLogger(__name__)

_store: ConversationStore = None       # 全局会话存储实例
_query_log_store: QueryLogStore = None # 全局查询日志存储实例
_feedback_store: FeedbackStore = None  # 全局反馈存储实例
_fault_progress_store: FaultProgressStore = None  # 阶段 2: 排查失败计数存储实例
_attachment_store: AttachmentStore = None
_ticket_store: TicketStore = None
_ticket_service = None                  # 阶段 5: 工单业务服务（Agent 建单胶水读取）


# 配置文件日志（轮转，UTF-8）
def _setup_file_logging() -> None:
    """在 lifespan 中调用，确保覆盖 uvicorn 的 dictConfig。

    P1-11: 用 RotatingFileHandler 替代 FileHandler，避免日志文件无限增长。
    配置：10MB 单文件上限，保留 5 份历史，UTF-8 编码。
    uvicorn 启动时用 dictConfig 配置日志会清除 basicConfig 的 handler，
    在 lifespan 中重新给 root logger 添加 RotatingFileHandler 确保错误日志落盘。
    """
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")  # 日志格式
    # P1-11: RotatingFileHandler 实现日志轮转（10MB × 5 份 = 最多 50MB）
    fh = RotatingFileHandler(            # 创建轮转处理器
        _log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"  # 10MB、5 份、UTF-8
    )
    fh.setFormatter(fmt)                 # 设置格式
    fh.setLevel(logging.INFO)            # 设置级别

    # root logger 添加 RotatingFileHandler
    root = logging.getLogger()           # 取根日志器
    root.addHandler(fh)                  # 添加文件处理器

    # app.* logger 确保传播到 root（不单独设置 propagate=False）
    for name in ("app", "app.api", "app.api.chat", "app.graph", "app.graph.tools", "app.graph.nodes"):
        lg = logging.getLogger(name)     # 取各子模块日志器
        lg.setLevel(logging.INFO)        # 统一设置级别


# 获取会话存储实例
def get_store() -> ConversationStore:
    if _store is None:                   # 尚未初始化
        raise RuntimeError("Store not initialized")  # 抛错
    return _store                        # 返回存储实例


# 获取查询日志存储实例
def get_query_log_store() -> QueryLogStore:
    """供 chat.py 落库用。允许返回 None：测试环境可能不初始化。

    chat.py 内部对 None 做兜底，避免单元测试必须 mock QueryLogStore。
    """
    return _query_log_store              # 直接返回（可能为 None）


# 获取反馈存储实例
def get_feedback_store() -> FeedbackStore:
    """供 feedback API 用。"""
    if _feedback_store is None:          # 尚未初始化
        raise RuntimeError("FeedbackStore not initialized")  # 抛错
    return _feedback_store               # 返回存储实例


# 获取排查失败计数存储实例（阶段 2: 人工升级建议）
def get_fault_progress_store() -> FaultProgressStore | None:
    """供 chat API 做排查失败计数用。允许返回 None：测试环境可能不初始化。"""
    return _fault_progress_store         # 直接返回（可能为 None）


def get_attachment_store() -> AttachmentStore | None:
    """供聊天请求读取当前轮显式选择的临时附件。"""
    return _attachment_store


def get_ticket_store() -> TicketStore:
    """Return the single-brand ticket store initialized by the lifespan."""
    if _ticket_store is None:
        raise RuntimeError("TicketStore not initialized")
    return _ticket_store


def get_ticket_service():
    """阶段 5: 供 chat 层在 decide_action 判定建单后调用（Agent 自动建草稿）。"""
    if _ticket_service is None:
        raise RuntimeError("TicketService not initialized")
    return _ticket_service


# 定义应用生命周期管理（启动初始化 / 关闭清理）
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store
    # 在 lifespan 中配置文件日志，覆盖 uvicorn 的 dictConfig
    _setup_file_logging()                # 配置日志
    logger.info("=== 应用启动 ===")      # 记录启动日志

    db_path = os.environ.get("TEST_SQLITE_PATH", settings.SQLITE_PATH)  # 测试可覆盖数据库路径
    _store = ConversationStore(db_path)  # 创建会话存储
    await _store.init()                  # 初始化数据库
    conversations.set_store(_store)      # 注入会话存储到路由

    global _attachment_store
    _attachment_store = AttachmentStore.from_settings(
        db_path,
        storage=LocalAttachmentStorage(settings.ATTACHMENT_STORAGE_DIR),
    )
    await _attachment_store.init()
    attachments.set_store(_attachment_store)

    global _ticket_store
    _ticket_store = TicketStore(db_path)
    await _ticket_store.init()

    # 第 1 阶段：query_log 表与 conversations 共享同一 db 文件，表结构独立
    global _query_log_store
    _query_log_store = QueryLogStore(db_path)  # 创建查询日志存储
    await _query_log_store.init()        # 初始化表
    logger.info("QueryLogStore 初始化完成")  # 记录日志

    # 工单业务服务：汇聚工单存储、会话快照、查询日志与附件证据
    # 阶段 5: 提升为模块级全局（get_ticket_service 供 chat 层 Agent 建单胶水读取）
    global _ticket_service
    _ticket_service = TicketService(
        ticket_store=_ticket_store,
        conversation_store=_store,
        query_log_store=_query_log_store,
        attachment_store=_attachment_store,
    )
    tickets.set_service(_ticket_service, _ticket_store)
    admin_tickets.set_service(_ticket_service, _ticket_store)

    auth_store = AuthStore(db_path)
    await auth_store.init(
        admin_username=settings.AUTH_ADMIN_USERNAME,
        admin_password=settings.AUTH_ADMIN_PASSWORD,
    )
    if await auth_store.count_active_admins() == 0 and not settings.AUTH_ADMIN_PASSWORD:
        raise ValueError("AUTH_ADMIN_PASSWORD is required")
    set_auth_store(auth_store)

    # 第 2 阶段：feedback 表与 query_log 表共享同一 db 文件，FK 关联
    global _feedback_store
    _feedback_store = FeedbackStore(db_path)  # 创建反馈存储
    await _feedback_store.init()         # 初始化表
    feedback.set_store(_feedback_store)  # 注入反馈存储到路由
    logger.info("FeedbackStore 初始化完成")  # 记录日志

    # 阶段 2: 排查失败计数（fault_progress 表），供人工升级建议判定
    global _fault_progress_store
    _fault_progress_store = FaultProgressStore(db_path)  # 创建排查计数存储
    await _fault_progress_store.init()  # 初始化表
    logger.info("FaultProgressStore 初始化完成")  # 记录日志

    # P0-3: Reranker 预热（GPU 加速，避免首次请求卡顿 2GB 模型加载）
    try:                                 # 尝试预热
        from app.rag.retriever import get_cross_encoder  # 延迟导入
        get_cross_encoder(settings.RERANKER_MODEL)  # 加载重排模型入缓存
        logger.info("Reranker 预热完成") # 记录日志
    except Exception as e:               # 预热失败
        logger.warning(f"Reranker 预热失败: {e}")  # 记录告警

    # 初始化 graph（失败降级到 None，不阻塞应用启动；chat 路由调用时再报错）
    try:                                 # 尝试初始化
        from app.rag.indexer import create_profiled_indexer  # 延迟导入索引器（按 KB_PROFILE 解析数据源）
        from app.graph.builder import build_graph  # 延迟导入图构建器
        from app.api import chat as chat_module  # 延迟导入聊天模块

        _indexer = create_profiled_indexer(  # 创建索引器
            persist_dir=settings.CHROMA_PERSIST_DIR,  # 持久化目录
        )
        _indexer.load_or_build()         # 加载或构建索引
        _graph = build_graph(_indexer.get_retriever())  # 构建工作流
        chat_module.set_graph(_graph)    # 注入图到聊天路由
        index_api.set_indexer(_indexer)  # 注入索引器到索引路由
        # 阶段 6: 管理端 AI Copilot——复用同一检索器装配工单分析服务
        from app.services.ticket_analysis_service import TicketAnalysisService  # 延迟导入
        from app.api import admin_tickets as admin_tickets_module  # 延迟导入

        admin_tickets_module.set_analysis_service(
            TicketAnalysisService(
                ticket_store=_ticket_store,
                conversation_store=_store,
                query_log_store=_query_log_store,
                attachment_store=_attachment_store,
                rag_retriever=_indexer.get_retriever(),
            )
        )
        logger.info("Graph 初始化成功")  # 记录日志
    except Exception as e:               # 初始化失败
        logger.warning(f"Graph 初始化失败（开发期可继续）: {e}")  # 降级告警

    yield                                # 让出控制权，应用运行
    logger.info("=== 应用关闭 ===")      # 记录关闭日志


# 创建 FastAPI 应用
app = FastAPI(title="无人机智能售后技术支持 Agent API", version="2.0.0", lifespan=lifespan)
# P1-10: 注册 slowapi 限速器和异常处理器
app.state.limiter = limiter              # 把限速器挂到应用状态
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # 限流超限统一响应
app.add_middleware(                      # 注册 CORS 中间件
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS, # 允许的来源
    allow_credentials=True,              # 允许携带凭证
    allow_methods=["*"],                 # 允许所有方法
    allow_headers=["*"],                 # 允许所有请求头
)
app.include_router(health.router)        # 挂载健康检查路由
app.include_router(auth.router)
app.include_router(conversations.router) # 挂载会话路由
app.include_router(attachments.router)   # 挂载临时附件路由
app.include_router(tickets.router)       # 挂载售后工单路由
app.include_router(admin_tickets.router) # 挂载管理员工单路由
app.include_router(feedback.router)      # 挂载反馈路由

# chat 模块依赖 get_store，必须在 get_store 定义后导入
from app.api import chat  # noqa: E402   # 延迟导入聊天模块（此时 get_store 已定义）

app.include_router(chat.router)          # 挂载聊天路由
app.include_router(index_api.router)     # 挂载索引路由
app.include_router(admin.router)

from app.api import graph as graph_api  # noqa: E402  # 延迟导入图谱路由

app.include_router(graph_api.router)     # 挂载图谱路由
register_error_handlers(app)             # 注册全局异常处理器
