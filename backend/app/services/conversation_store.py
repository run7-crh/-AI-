# backend/app/services/conversation_store.py
# 导入 aiosqlite，异步操作 SQLite
import aiosqlite
# 导入 sqlite3，用于同步操作/异常类型与 PRAGMA 配置
import sqlite3
# 导入 uuid4，用于生成会话/消息的唯一 id
from uuid import uuid4
# 导入 datetime 与 timezone，用于生成 UTC 时间戳
from datetime import datetime, timezone
# 导入 Path，用于创建数据库目录
from pathlib import Path
# 导入 json，用于序列化消息中的列表字段
import json
# 导入日志模块
import logging
# 导入 Optional，用于类型标注
from typing import Optional
# 导入 tenacity 重试组件：重试、停止条件、退避策略、异常类型过滤
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.models.attachment import ATTACHMENT_SCHEMA_SQL

# 获取当前模块日志器
logger = logging.getLogger(__name__)


# 定义数据库连接级安全配置函数
async def _configure_db(db: aiosqlite.Connection) -> None:
    """Apply connection-local safety settings consistently."""
    await db.execute("PRAGMA foreign_keys = ON")  # 开启外键约束
    await db.execute("PRAGMA busy_timeout = 5000")  # 忙时等待 5 秒

# 建表 SQL（字符串字面量，内容保持原样，仅注释外围语句）
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    title TEXT NOT NULL DEFAULT '新会话',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    message_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    route_path TEXT,
    sources TEXT,
    judge_log TEXT,
    quality_warning TEXT,
    query_log_id TEXT,
    safety_flag INTEGER,
    safety_level TEXT,
    safety_situation TEXT,
    escalation_required INTEGER,
    intent TEXT,
    metadata_constraints TEXT,
    document_type_priority TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
"""

# P1-4: SQLite 并发写入时可能抛 OperationalError("database is locked")
# 短退避重试 3 次可解决典型并发冲突，避免用户偶发失败
_db_retry = retry(                                       # 定义数据库操作重试装饰器
    stop=stop_after_attempt(3),                          # 最多重试 3 次
    wait=wait_exponential(multiplier=0.1, min=0.1, max=1.0),  # 指数退避等待 0.1~1 秒
    retry=retry_if_exception_type(sqlite3.OperationalError),  # 仅重试锁冲突错误
    reraise=True,                                        # 耗尽重试后重抛原异常
)


# 定义会话存储类，封装话务的持久化操作
class ConversationStore:
    # 初始化：保存数据库路径并确保目录存在
    def __init__(self, db_path: str):
        self.db_path = db_path                           # 数据库文件路径
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)  # 确保父目录存在

    # 初始化数据库：建表并做旧库迁移
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            await db.execute("PRAGMA journal_mode = WAL")  # 启用 WAL 日志模式提升并发
            await db.executescript(SCHEMA_SQL)           # 执行建表脚本
            # Temporary user attachments live in their own tables.  Keeping
            # this migration here makes old SQLite databases start without a
            # reset while leaving messages/query_log payloads unchanged.
            await db.executescript(ATTACHMENT_SCHEMA_SQL)
            # Existing local databases predate the two response metadata
            # columns.  Migrate in place so conversation history remains
            # readable without requiring a destructive reset.
            cursor = await db.execute("PRAGMA table_info(messages)")  # 读取 messages 表结构
            columns = {row[1] for row in await cursor.fetchall()}     # 提取现有列名
            conv_cursor = await db.execute("PRAGMA table_info(conversations)")
            conv_columns = {row[1] for row in await conv_cursor.fetchall()}
            if "user_id" not in conv_columns:
                await db.execute("ALTER TABLE conversations ADD COLUMN user_id TEXT")
            migration_columns = {
                "user_id": "TEXT",
                "quality_warning": "TEXT",
                "query_log_id": "TEXT",
                "safety_flag": "INTEGER",
                "safety_level": "TEXT",
                "safety_situation": "TEXT",
                "escalation_required": "INTEGER",
                "intent": "TEXT",
                "metadata_constraints": "TEXT",
                "document_type_priority": "TEXT",
            }
            attachment_cursor = await db.execute("PRAGMA table_info(attachments)")
            attachment_columns = {row[1] for row in await attachment_cursor.fetchall()}
            for name, definition in {
                "extracted_chars": "INTEGER",
                "extraction_error": "TEXT",
                "extraction_summary": "TEXT",
            }.items():
                if name not in attachment_columns:
                    await db.execute(f"ALTER TABLE attachments ADD COLUMN {name} {definition}")
            for name, definition in migration_columns.items():
                if name not in columns:                  # 旧库缺此列
                    await db.execute(f"ALTER TABLE messages ADD COLUMN {name} {definition}")  # 动态加列
            await db.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id)")
            await db.commit()                            # 提交迁移

    # 创建新会话
    @_db_retry
    async def create_conversation(self, title: Optional[str] = None, user_id: Optional[str] = None) -> str:
        conv_id = str(uuid4())                           # 生成会话 id
        now = datetime.now(timezone.utc).isoformat()     # 生成 UTC 时间戳
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            await db.execute(                            # 插入会话记录
                "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conv_id, user_id, title or "新会话", now, now),  # 默认标题"新会话"
            )
            await db.commit()                            # 提交
        return conv_id                                   # 返回新会话 id

    # 查询会话列表（按最近更新倒序）
    @_db_retry
    async def list_conversations(self, user_id: Optional[str] = None) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            # ISO timestamps can collide when two writes happen within the
            # clock's precision.  rowid is the insertion sequence for this
            # table and provides deterministic newest-first ordering on ties.
            query = "SELECT * FROM conversations"
            params = ()
            if user_id is not None:
                query += " WHERE user_id = ?"
                params = (user_id,)
            query += " ORDER BY updated_at DESC, rowid DESC"
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()               # 取全部行
            return [dict(row) for row in rows]           # 转字典列表

    # 获取单个会话详情（含消息）
    @_db_retry
    async def get_conversation(self, conv_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            query = "SELECT * FROM conversations WHERE id = ?"
            params = [conv_id]
            if user_id is not None:
                query += " AND user_id = ?"
                params.append(user_id)
            cursor = await db.execute(query, params)  # 查会话
            conv = await cursor.fetchone()               # 取第一条
            if not conv:                                 # 会话不存在
                return None                              # 返回 None
            cursor = await db.execute(                   # 查该会话全部消息（按时间正序）
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conv_id,),
            )
            messages = await cursor.fetchall()           # 取消息行
            result = dict(conv)                          # 会话字段转字典
            result["messages"] = [dict(m) for m in messages]  # 消息行转字典列表
            # Historical messages expose only bounded attachment metadata.
            # The payload and storage key stay private and are never copied
            # into messages or query_log.
            attachments_by_message: dict[str, list[dict]] = {}
            try:
                attachment_cursor = await db.execute(
                    """SELECT ma.message_id, a.id, a.original_name, a.extension,
                              a.declared_mime, a.detected_mime, a.size_bytes,
                              a.status, a.extraction_status, a.extracted_chars,
                              a.extraction_error, a.scan_status, a.created_at, a.expires_at,
                              a.deleted_at
                       FROM message_attachments ma
                       JOIN attachments a ON a.id = ma.attachment_id
                       JOIN messages linked ON linked.id = ma.message_id
                       WHERE linked.conversation_id = ?
                       ORDER BY ma.created_at ASC""",
                    (conv_id,),
                )
                for row in await attachment_cursor.fetchall():
                    attachments_by_message.setdefault(row[0], []).append({
                        "id": row[1],
                        "attachment_id": row[1],
                        "original_name": row[2],
                        "extension": row[3],
                        "declared_mime": row[4],
                        "detected_mime": row[5],
                        "size_bytes": int(row[6]),
                        "status": row[7],
                        "extraction_status": row[8],
                        "extracted_chars": row[9],
                        "extraction_error": row[10],
                        "scan_status": row[11],
                        "created_at": row[12],
                        "expires_at": row[13],
                        "deleted_at": row[14],
                    })
            except sqlite3.OperationalError as exc:
                # A caller may inspect a database created before attachment
                # tables existed and before the normal init migration ran.
                if "no such table" not in str(exc).lower():
                    raise
            for m in result["messages"]:
                m["attachments"] = attachments_by_message.get(m["id"], [])
            for m in result["messages"]:                 # 遍历每个消息
                if m.get("sources"):                     # 有 sources 字段
                    m["sources"] = json.loads(m["sources"])  # 反序列化还原为列表
                if m.get("judge_log"):                   # 有 judge_log 字段
                    m["judge_log"] = json.loads(m["judge_log"])  # 反序列化还原
                for name in ("metadata_constraints", "document_type_priority"):
                    if m.get(name):
                        m[name] = json.loads(m[name])
                for name in ("safety_flag", "escalation_required"):
                    if m.get(name) is not None:
                        m[name] = bool(m[name])
            return result                                # 返回带消息的会话

    # 向会话追加一条消息并更新会话计数
    @_db_retry
    async def add_message(
        self,
        conv_id,                   # 会话 id
        role,                      # 角色
        content,                   # 内容
        route_path=None,           # 路由路径（可选）
        sources=None,              # 来源列表（可选）
        judge_log=None,            # 判断日志（可选）
        quality_warning=None,      # 质量告警（可选）
        query_log_id=None,         # 查询日志 id（可选）
        safety_flag=None,           # 安全标记（可选）
        safety_level=None,          # 安全等级（可选）
        safety_situation=None,      # 设备状态（可选）
        escalation_required=None,   # 是否建议升级人工（可选）
        intent=None,                # 意图分类（可选）
        metadata_constraints=None,  # 检索约束（可选）
        document_type_priority=None,# 文档类型优先级（可选）
    ) -> str:
        """P1-4: 显式事务保证 INSERT message + UPDATE conversation 原子性。

        aiosqlite 默认 isolation_level=None 时每条语句自动 BEGIN，
        await db.commit() 一次性提交两条语句，等价于显式事务。
        重试装饰器覆盖 "database is locked" 场景。
        """
        msg_id = str(uuid4())                            # 生成消息 id
        now = datetime.now(timezone.utc).isoformat()     # 生成 UTC 时间戳
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            await db.execute(                            # 插入消息记录
                """INSERT INTO messages
                   (id, conversation_id, role, content, route_path, sources,
                   judge_log, quality_warning, query_log_id, safety_flag,
                   safety_level, safety_situation, escalation_required, intent,
                   metadata_constraints, document_type_priority, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, conv_id, role, content, route_path,
                 json.dumps(sources) if sources else None,   # 来源序列化为 JSON 或 NULL
                 json.dumps(judge_log) if judge_log else None,  # 判断日志序列化或 NULL
                 quality_warning, query_log_id,
                 None if safety_flag is None else int(bool(safety_flag)),
                 safety_level, safety_situation,
                 None if escalation_required is None else int(bool(escalation_required)),
                 intent,
                 json.dumps(metadata_constraints, ensure_ascii=False) if metadata_constraints is not None else None,
                 json.dumps(document_type_priority, ensure_ascii=False) if document_type_priority is not None else None,
                 now),
            )
            await db.execute(                            # 更新会话时间与消息计数
                "UPDATE conversations SET updated_at = ?, message_count = message_count + 1 WHERE id = ?",
                (now, conv_id),
            )
            await db.commit()                            # 一并提交两条语句
        return msg_id                                    # 返回新消息 id

    # 删除会话（连带其消息与日志）
    @_db_retry
    async def delete_conversation(self, conv_id: str, user_id: Optional[str] = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            check = "SELECT 1 FROM conversations WHERE id = ?"
            check_params = [conv_id]
            if user_id is not None:
                check += " AND user_id = ?"
                check_params.append(user_id)
            exists = await (await db.execute(check, check_params)).fetchone()
            if exists is None:
                return False
            await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))  # 删消息
            # query_log predates the conversation FK and may exist without ON DELETE CASCADE.
            # Remove diagnostic records explicitly while keeping the store usable in tests
            # or older databases where query_log has not been created yet.
            try:                                         # 尝试删除诊断日志
                await db.execute("DELETE FROM query_log WHERE conversation_id = ?", (conv_id,))
            except sqlite3.OperationalError as exc:      # 日志表可能不存在
                if "no such table" not in str(exc).lower():  # 非缺表错误
                    raise                               # 重抛
            cursor = await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))  # 删会话
            await db.commit()                            # 提交
            return cursor.rowcount > 0                   # 是否确实删除了记录

    # 更新会话标题
    @_db_retry
    async def update_conversation_title(self, conv_id, title, user_id: Optional[str] = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()     # 生成 UTC 时间戳
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            query = "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?"
            params = [title, now, conv_id]
            if user_id is not None:
                query += " AND user_id = ?"
                params.append(user_id)
            cursor = await db.execute(query, params)
            await db.commit()                            # 提交
            return cursor.rowcount > 0                   # 是否有行被更新

    # 获取最近若干条消息作为上下文（倒序取再正序返回）
    @_db_retry
    async def get_history(self, conv_id: str, limit: int = 10, user_id: Optional[str] = None) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            query = "SELECT m.role, m.content FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE m.conversation_id = ?"
            params = [conv_id]
            if user_id is not None:
                query += " AND c.user_id = ?"
                params.append(user_id)
            query += " ORDER BY m.created_at DESC LIMIT ?"
            params.append(limit)
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()               # 取查询结果
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]  # 反转为时间正序
