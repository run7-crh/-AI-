# backend/app/services/query_log_service.py
"""用户请求全链路日志写入服务。

设计原则：
- 复用 ConversationStore 的 _db_retry 装饰器（同一 db 文件，同一并发冲突场景）
- 表结构独立于 conversations/messages（避免影响现有 118 个测试）
- 写入失败不抛异常拖垮 chat 响应（调用方在 finally 中再 try/except）

诊断用途：
- list_recent：按时间倒序排查延迟异常
- get_by_conversation：按会话查轨迹（诊断"某次对话为何路由错"）
- get_by_route：按路由路径筛（统计 local/online/decomposition 分布）
"""
# 导入 json，用于序列化字段
import json
# 导入日志模块
import logging
# 导入 Path，用于创建数据库目录
from pathlib import Path
# 导入 Optional，用于类型标注
from typing import Optional

# 导入 aiosqlite，异步操作 SQLite
import aiosqlite

# 复用 ConversationStore 的重试装饰器（同一 db 文件，同一并发冲突场景）
from app.services.conversation_store import _db_retry, _configure_db

# 导入查询日志数据模型
from app.models.query_log import QueryLogCreate

# 获取当前模块日志器
logger = logging.getLogger(__name__)

# 查询日志表建表 SQL（字符串字面量，内容保持原样，仅注释外围语句）
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS query_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id TEXT,
    user_label TEXT,
    raw_query TEXT NOT NULL,
    rewritten_query TEXT,
    route_path TEXT,
    rewrite_count INTEGER DEFAULT 0,
    retrieved_doc_ids TEXT,
    avg_reranker_score REAL,
    judge_log_json TEXT,
    final_answer TEXT,
    answer_length INTEGER,
    has_source INTEGER,
    models_used_json TEXT,
    token_usage_json TEXT,
    fault_key TEXT,
    safety_flag INTEGER,
    safety_level TEXT,
    safety_situation TEXT,
    escalation_required INTEGER,
    intent TEXT,
    metadata_constraints TEXT,
    document_type_priority TEXT,
    latency_ms INTEGER,
    error TEXT,
    created_at TEXT NOT NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_query_log_conversation ON query_log(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_query_log_route ON query_log(route_path);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);
CREATE INDEX IF NOT EXISTS idx_query_log_fault_key ON query_log(conversation_id, fault_key);
"""


# 定义查询日志表访问层
class QueryLogStore:
    """query_log 表的访问层。

    与 ConversationStore 共享同一 SQLite 文件（db_path 一致），
    但表结构独立，互不影响。
    """

    # 初始化：保存数据库路径
    def __init__(self, db_path: str):
        self.db_path = db_path                           # 数据库文件路径
        # 确保父目录存在（与 ConversationStore 一致行为）
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)  # 确保父目录存在

    # 初始化：建表（幂等），在 lifespan 中调用一次
    async def init(self):
        """建表（幂等）。在 lifespan 中调用一次。

        兼容旧库：先补齐新列，再创建依赖这些列的索引。
        """
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            await db.execute("PRAGMA journal_mode = WAL")  # 启用 WAL 日志模式
            await db.executescript(SCHEMA_SQL)           # 先确保表存在
            cursor = await db.execute("PRAGMA table_info(query_log)")
            existing = {row[1] for row in await cursor.fetchall()}
            # 老版本只包含基础字段；所有新增列均可空或有默认值，适合在线迁移。
            migration_columns = {
                "user_id": "TEXT",
                "user_label": "TEXT",
                "rewritten_query": "TEXT",
                "route_path": "TEXT",
                "rewrite_count": "INTEGER DEFAULT 0",
                "retrieved_doc_ids": "TEXT",
                "avg_reranker_score": "REAL",
                "judge_log_json": "TEXT",
                "final_answer": "TEXT",
                "answer_length": "INTEGER DEFAULT 0",
                "has_source": "INTEGER DEFAULT 0",
                "models_used_json": "TEXT",
                "token_usage_json": "TEXT",
                "fault_key": "TEXT",
                "safety_flag": "INTEGER",
                "safety_level": "TEXT",
                "safety_situation": "TEXT",
                "escalation_required": "INTEGER",
                "intent": "TEXT",
                "metadata_constraints": "TEXT",
                "document_type_priority": "TEXT",
                "latency_ms": "INTEGER",
                "error": "TEXT",
            }
            for name, definition in migration_columns.items():
                if name not in existing:
                    await db.execute(f"ALTER TABLE query_log ADD COLUMN {name} {definition}")
            await db.executescript(INDEX_SQL)           # 列齐全后再创建索引
            await db.commit()                            # 提交

    # 一次性插入整条日志
    @_db_retry
    async def insert(self, record: QueryLogCreate) -> str:
        """一次性 INSERT 整条日志记录。

        Returns:
            record.id（写入成功后回传，便于调用方关联）
        Raises:
            sqlite3.OperationalError: 重试 3 次仍冲突时抛出（由调用方兜底）
        """
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            await db.execute(                            # 插入完整日志记录
                """INSERT INTO query_log
                   (id, conversation_id, user_id, user_label, raw_query, rewritten_query,
                    route_path, rewrite_count, retrieved_doc_ids, avg_reranker_score,
                    judge_log_json, final_answer, answer_length, has_source,
                    models_used_json, token_usage_json, fault_key, safety_flag,
                    safety_level, safety_situation, escalation_required, intent,
                    metadata_constraints, document_type_priority, latency_ms, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,                           # 日志 id
                    record.conversation_id,              # 会话 id
                    record.user_id,
                    record.user_label,                   # 提问者标识
                    record.raw_query,                    # 原始问题
                    record.rewritten_query,              # 改写后查询
                    record.route_path,                   # 路由路径
                    record.rewrite_count,                # 改写次数
                    record.retrieved_doc_ids,            # 检索文档 id
                    record.avg_reranker_score,           # 重排平均分
                    record.judge_log_json,               # 判断日志
                    record.final_answer,                 # 最终回答
                    record.answer_length,                # 回答长度
                    record.has_source,                   # 是否含来源
                    record.models_used_json,             # 用到的模型
                    record.token_usage_json,             # token 用量
                    record.fault_key,                    # 阶段 2: 故障标识
                    None if record.safety_flag is None else int(bool(record.safety_flag)),
                    record.safety_level,
                    record.safety_situation,
                    None if record.escalation_required is None else int(bool(record.escalation_required)),
                    record.intent,
                    json.dumps(record.metadata_constraints, ensure_ascii=False) if record.metadata_constraints is not None else None,
                    json.dumps(record.document_type_priority, ensure_ascii=False) if record.document_type_priority is not None else None,
                    record.latency_ms,                   # 延迟毫秒数
                    record.error,                        # 异常描述
                    record.created_at,                   # 创建时间
                ),
            )
            await db.commit()                            # 提交
        return record.id                                 # 回传日志 id

    @_db_retry
    async def delete_by_user(self, user_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            await db.execute("DELETE FROM query_log WHERE user_id=?", (user_id,)); await db.commit()

    # 查询会话内最近一条带 fault_key 的日志（排查失败计数用）
    @_db_retry
    async def get_latest_fault_key(self, conv_id: str) -> Optional[dict]:
        """取会话内最近一条 fault_key 非空的日志（id + fault_key）。

        阶段 2: 用户"确认执行仍无效"时，据此定位要累加的故障标识。
        无记录返回 None。
        """
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            cursor = await db.execute(                   # 最近一条带 fault_key 的记录
                """SELECT id, fault_key FROM query_log
                   WHERE conversation_id = ? AND fault_key IS NOT NULL
                   ORDER BY created_at DESC LIMIT 1""",
                (conv_id,),
            )
            row = await cursor.fetchone()                # 取一行
            return dict(row) if row else None            # 转字典（无记录返回 None）

    # 按时间倒序查最近 N 条
    @_db_retry
    async def list_recent(self, limit: int = 100) -> list[dict]:
        """按时间倒序查最近 N 条（诊断延迟异常用）。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            cursor = await db.execute(                   # 按时间倒序取 limit 条
                "SELECT * FROM query_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()               # 取结果
            return [dict(r) for r in rows]               # 转字典列表

    # 按会话 ID 查询全部日志
    @_db_retry
    async def get_by_conversation(self, conv_id: str) -> list[dict]:
        """按会话 ID 查询全部日志（诊断"某次对话为何路由错"用）。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            cursor = await db.execute(                   # 按会话查询，时间正序
                "SELECT * FROM query_log WHERE conversation_id = ? ORDER BY created_at ASC",
                (conv_id,),
            )
            rows = await cursor.fetchall()               # 取结果
            return [dict(r) for r in rows]               # 转字典列表

    # 按路由路径筛选
    @_db_retry
    async def get_by_route(self, route_path: str, limit: int = 100) -> list[dict]:
        """按路由路径筛选（统计 local/online/decomposition 分布）。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            cursor = await db.execute(                   # 按路径查询并按时间倒序
                "SELECT * FROM query_log WHERE route_path = ? ORDER BY created_at DESC LIMIT ?",
                (route_path, limit),
            )
            rows = await cursor.fetchall()               # 取结果
            return [dict(r) for r in rows]               # 转字典列表

    # 轻量计数探测
    @_db_retry
    async def count(self) -> int:
        """轻量探测，用于健康检查。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            cursor = await db.execute("SELECT COUNT(*) FROM query_log")  # 统计记录数
            row = await cursor.fetchone()                # 取一行
            return row[0] if row else 0                  # 返回计数（无记录返回 0）
