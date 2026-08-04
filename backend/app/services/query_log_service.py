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
import json
import logging
from pathlib import Path
from typing import Optional

import aiosqlite

# 复用 ConversationStore 的重试装饰器（同一 db 文件，同一并发冲突场景）
from app.services.conversation_store import _db_retry

from app.models.query_log import QueryLogCreate

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS query_log (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
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
    latency_ms INTEGER,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_log_conversation ON query_log(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_query_log_route ON query_log(route_path);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);
"""


class QueryLogStore:
    """query_log 表的访问层。

    与 ConversationStore 共享同一 SQLite 文件（db_path 一致），
    但表结构独立，互不影响。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        # 确保父目录存在（与 ConversationStore 一致行为）
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init(self):
        """建表（幂等）。在 lifespan 中调用一次。"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()

    @_db_retry
    async def insert(self, record: QueryLogCreate) -> str:
        """一次性 INSERT 整条日志记录。

        Returns:
            record.id（写入成功后回传，便于调用方关联）
        Raises:
            sqlite3.OperationalError: 重试 3 次仍冲突时抛出（由调用方兜底）
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO query_log
                   (id, conversation_id, user_label, raw_query, rewritten_query,
                    route_path, rewrite_count, retrieved_doc_ids, avg_reranker_score,
                    judge_log_json, final_answer, answer_length, has_source,
                    models_used_json, token_usage_json, latency_ms, error, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.conversation_id,
                    record.user_label,
                    record.raw_query,
                    record.rewritten_query,
                    record.route_path,
                    record.rewrite_count,
                    record.retrieved_doc_ids,
                    record.avg_reranker_score,
                    record.judge_log_json,
                    record.final_answer,
                    record.answer_length,
                    record.has_source,
                    record.models_used_json,
                    record.token_usage_json,
                    record.latency_ms,
                    record.error,
                    record.created_at,
                ),
            )
            await db.commit()
        return record.id

    @_db_retry
    async def list_recent(self, limit: int = 100) -> list[dict]:
        """按时间倒序查最近 N 条（诊断延迟异常用）。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM query_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    @_db_retry
    async def get_by_conversation(self, conv_id: str) -> list[dict]:
        """按会话 ID 查询全部日志（诊断"某次对话为何路由错"用）。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM query_log WHERE conversation_id = ? ORDER BY created_at ASC",
                (conv_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    @_db_retry
    async def get_by_route(self, route_path: str, limit: int = 100) -> list[dict]:
        """按路由路径筛选（统计 local/online/decomposition 分布）。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM query_log WHERE route_path = ? ORDER BY created_at DESC LIMIT ?",
                (route_path, limit),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    @_db_retry
    async def count(self) -> int:
        """轻量探测，用于健康检查。"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM query_log")
            row = await cursor.fetchone()
            return row[0] if row else 0
