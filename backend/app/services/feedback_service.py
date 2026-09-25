# backend/app/services/feedback_service.py
"""用户反馈写入与统计服务。

设计原则：
- 复用 ConversationStore 的 _db_retry 装饰器（同一 db 文件）
- feedback 表与 query_log 表通过 FOREIGN KEY 关联（共享同一 db 文件）
- upsert 语义：UNIQUE(query_log_id)，INSERT ... ON CONFLICT DO UPDATE
- 外键校验：upsert 前先查 query_log 表，不存在抛 ValueError（api 层转 404）
"""
# 导入日志模块
import logging
# 导入 Path，用于创建数据库目录
from pathlib import Path
# 导入 uuid4，用于生成反馈 id
from uuid import uuid4
# 导入 datetime 与 timezone，用于生成 UTC 时间戳
from datetime import datetime, timezone
# 导入 Optional，用于类型标注
from typing import Optional

# 导入 aiosqlite，异步操作 SQLite
import aiosqlite

# 复用 ConversationStore 的重试装饰器与连接配置函数
from app.services.conversation_store import _db_retry, _configure_db

# 导入反馈请求数据模型
from app.models.feedback import FeedbackCreate

# 获取当前模块日志器
logger = logging.getLogger(__name__)

# 反馈表建表 SQL（字符串字面量，内容保持原样，仅注释外围语句）
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


# 定义反馈表访问层
class FeedbackStore:
    """feedback 表的访问层。

    与 query_log 表共享同一 SQLite 文件（db_path 一致）。
    """

    # 初始化：保存数据库路径并确保目录存在
    def __init__(self, db_path: str):
        self.db_path = db_path                           # 数据库文件路径
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)  # 确保父目录存在

    # 初始化：建表（幂等），在 lifespan 中调用一次
    async def init(self):
        """建表（幂等）。在 lifespan 中调用一次。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            await db.executescript(SCHEMA_SQL)           # 执行建表脚本
            await db.commit()                            # 提交

    # 校验 query_log_id 是否存在
    async def _query_log_exists(self, db: aiosqlite.Connection, query_log_id: str, user_id: str | None = None) -> bool:
        """校验 query_log_id 存在性（外键约束的显式校验，便于返回 404）。"""
        query = "SELECT 1 FROM query_log WHERE id = ?"
        params = [query_log_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        cursor = await db.execute(query, params)  # 探测记录
        row = await cursor.fetchone()                    # 取一条
        return row is not None                           # 存在则 True

    # upsert 一条反馈记录
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
        if record.rating == 'useless' and not record.useless_reason:  # 无用打分但缺原因
            raise ValueError("rating='useless' 时 useless_reason 必填")  # 抛参数错误

        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            # 外键校验（返回友好 404，而非 sqlite3.IntegrityError）
            if not await self._query_log_exists(db, record.query_log_id, user_id):  # 日志记录不存在
                raise ValueError(f"query_log_id 不存在: {record.query_log_id}")  # 抛 404 前置错误

            feedback_id = str(uuid4())                   # 生成反馈 id
            now = datetime.now(timezone.utc).isoformat() # 生成 UTC 时间戳

            # upsert：query_log_id 冲突时更新 rating/useless_reason/comment/created_at
            # ON CONFLICT(query_log_id) DO UPDATE 子句中，excluded 表示"新插入的值"
            cursor = await db.execute(                   # 执行插入或更新
                """INSERT INTO feedback (id, query_log_id, rating, useless_reason, comment, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(query_log_id) DO UPDATE SET
                       rating = excluded.rating,
                       useless_reason = excluded.useless_reason,
                       comment = excluded.comment,
                       created_at = excluded.created_at""",
                (
                    feedback_id,                         # 新反馈 id
                    record.query_log_id,                 # 被反馈的日志 id
                    record.rating,                       # 打分
                    record.useless_reason,               # 无用原因
                    record.comment,                      # 文字补充
                    now,                                 # 时间戳
                ),
            )
            await db.commit()                            # 提交

            # ON CONFLICT 触发更新时，cursor.lastrowid 不可靠，回查 id
            if cursor.lastrowid == 0:                    # lastrowid 缺失（触发的是更新）
                cur2 = await db.execute(                 # 按日志 id 回查反馈 id
                    "SELECT id FROM feedback WHERE query_log_id = ?",
                    (record.query_log_id,),
                )
                row = await cur2.fetchone()              # 取一行
                feedback_id = row[0] if row else feedback_id  # 用真实 id（查不到则保留原值）

            return feedback_id                           # 返回反馈 id

    # 统计反馈数据
    @_db_retry
    async def get_stats(self) -> dict:
        """统计反馈数据，供 GET /api/feedback/stats 返回。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            # 总数
            cursor = await db.execute("SELECT COUNT(*) FROM feedback")  # 统计全部记录数
            total = (await cursor.fetchone())[0]         # 取总数

            # 按 rating 分组
            cursor = await db.execute(                   # 按打分维度分组计数
                "SELECT rating, COUNT(*) FROM feedback GROUP BY rating"
            )
            rating_counts = {row[0]: row[1] for row in await cursor.fetchall()}  # 构造打分计数映射

            # useless_reason 分组（仅 rating='useless' 的记录）
            cursor = await db.execute(                   # 无用原因维度分组计数
                """SELECT useless_reason, COUNT(*) FROM feedback
                   WHERE rating = 'useless' AND useless_reason IS NOT NULL
                   GROUP BY useless_reason"""
            )
            reason_counts = {row[0]: row[1] for row in await cursor.fetchall()}  # 构造原因计数映射

            return {                                     # 组装统计结果
                "total": total,                          # 总数
                "useful_count": rating_counts.get("useful", 0),  # 有帮助数
                "useless_count": rating_counts.get("useless", 0),  # 无帮助数
                "bug_count": rating_counts.get("bug", 0),  # 错误数
                "useless_reason_breakdown": {            # 无用原因分布
                    "irrelevant": reason_counts.get("irrelevant", 0),  # 不相关
                    "hallucination": reason_counts.get("hallucination", 0),  # 幻觉
                    "verbose": reason_counts.get("verbose", 0),  # 冗长
                    "wrong_route": reason_counts.get("wrong_route", 0),  # 路由错误
                },
            }

    # 按 query_log_id 查询反馈
    @_db_retry
    async def get_by_query_log_id(self, query_log_id: str) -> Optional[dict]:
        """按 query_log_id 查反馈（用于未来前端持久化反馈状态）。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            cursor = await db.execute(                   # 按日志 id 查询
                "SELECT * FROM feedback WHERE query_log_id = ?",
                (query_log_id,),
            )
            row = await cursor.fetchone()                # 取一行
            return dict(row) if row else None            # 有则转字典，否则 None
