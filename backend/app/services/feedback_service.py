# backend/app/services/feedback_service.py
"""用户反馈写入与统计服务。

设计原则：
- 复用 ConversationStore 的 _db_retry 装饰器（同一 db 文件）
- feedback 表与 query_log 表通过 FOREIGN KEY 关联（共享同一 db 文件）
- upsert 语义：UNIQUE(query_log_id)，INSERT ... ON CONFLICT DO UPDATE
- 外键校验：upsert 前先查 query_log 表，不存在抛 ValueError（api 层转 404）
"""
import logging
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

# 复用 ConversationStore 的重试装饰器
from app.services.conversation_store import _db_retry

from app.models.feedback import FeedbackCreate

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    query_log_id TEXT NOT NULL,
    rating TEXT NOT NULL,
    useless_reason TEXT,
    comment TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (query_log_id) REFERENCES query_log(id) ON DELETE CASCADE,
    UNIQUE(query_log_id)
);

CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at);
"""


class FeedbackStore:
    """feedback 表的访问层。

    与 query_log 表共享同一 SQLite 文件（db_path 一致）。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init(self):
        """建表（幂等）。在 lifespan 中调用一次。"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()

    async def _query_log_exists(
        self, db: aiosqlite.Connection, query_log_id: str, user_id: str | None = None
    ) -> bool:
        """校验 query_log_id 存在性（外键约束的显式校验，便于返回 404）。"""
        query = "SELECT 1 FROM query_log WHERE id = ?"
        params = [query_log_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        return row is not None

    @_db_retry
    async def upsert(self, record: FeedbackCreate, user_id: str | None = None) -> str:
        """upsert 反馈记录。

        Returns:
            feedback_id
        Raises:
            ValueError: query_log_id 不存在（外键校验失败）
            sqlite3.OperationalError: 重试 3 次仍冲突
        """
        # 业务校验：rating='useless' 时 useless_reason 必填
        if record.rating == 'useless' and not record.useless_reason:
            raise ValueError("rating='useless' 时 useless_reason 必填")

        async with aiosqlite.connect(self.db_path) as db:
            # 外键校验（返回友好 404，而非 sqlite3.IntegrityError）
            if not await self._query_log_exists(db, record.query_log_id, user_id):
                raise ValueError(f"query_log_id 不存在: {record.query_log_id}")

            feedback_id = str(uuid4())
            now = datetime.now(timezone.utc).isoformat()

            # upsert：query_log_id 冲突时更新 rating/useless_reason/comment/created_at
            # ON CONFLICT(query_log_id) DO UPDATE 子句中，excluded 表示"新插入的值"
            cursor = await db.execute(
                """INSERT INTO feedback (id, query_log_id, rating, useless_reason, comment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(query_log_id) DO UPDATE SET
                       rating = excluded.rating,
                       useless_reason = excluded.useless_reason,
                       comment = excluded.comment,
                       created_at = excluded.created_at""",
                (
                    feedback_id,
                    record.query_log_id,
                    record.rating,
                    record.useless_reason,
                    record.comment,
                    now,
                ),
            )
            await db.commit()

            # ON CONFLICT 触发更新时，cursor.lastrowid 不可靠，回查 id
            if cursor.lastrowid == 0:
                cur2 = await db.execute(
                    "SELECT id FROM feedback WHERE query_log_id = ?",
                    (record.query_log_id,),
                )
                row = await cur2.fetchone()
                feedback_id = row[0] if row else feedback_id

            return feedback_id

    @_db_retry
    async def get_stats(self) -> dict:
        """统计反馈数据，供 GET /api/feedback/stats 返回。"""
        async with aiosqlite.connect(self.db_path) as db:
            # 总数
            cursor = await db.execute("SELECT COUNT(*) FROM feedback")
            total = (await cursor.fetchone())[0]

            # 按 rating 分组
            cursor = await db.execute(
                "SELECT rating, COUNT(*) FROM feedback GROUP BY rating"
            )
            rating_counts = {row[0]: row[1] for row in await cursor.fetchall()}

            # useless_reason 分组（仅 rating='useless' 的记录）
            cursor = await db.execute(
                """SELECT useless_reason, COUNT(*) FROM feedback
                   WHERE rating = 'useless' AND useless_reason IS NOT NULL
                   GROUP BY useless_reason"""
            )
            reason_counts = {row[0]: row[1] for row in await cursor.fetchall()}

            return {
                "total": total,
                "useful_count": rating_counts.get("useful", 0),
                "useless_count": rating_counts.get("useless", 0),
                "bug_count": rating_counts.get("bug", 0),
                "useless_reason_breakdown": {
                    "irrelevant": reason_counts.get("irrelevant", 0),
                    "hallucination": reason_counts.get("hallucination", 0),
                    "verbose": reason_counts.get("verbose", 0),
                    "wrong_route": reason_counts.get("wrong_route", 0),
                },
            }

    @_db_retry
    async def get_by_query_log_id(self, query_log_id: str) -> Optional[dict]:
        """按 query_log_id 查反馈（用于未来前端持久化反馈状态）。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM feedback WHERE query_log_id = ?",
                (query_log_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
