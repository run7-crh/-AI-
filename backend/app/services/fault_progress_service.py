# backend/app/services/fault_progress_service.py
"""排查失败计数的可持久化存储（阶段 2：人工升级建议）。

设计要点（区别于"聊天轮数 / query_log 条数"的粗略统计）：
- 计数粒度是"同一会话 + 同一故障标识（fault_key，机型__故障类型）"，
  只有用户消息同时命中"已按步骤执行"与"仍无效"两类信号才累加 1 次；
- fault_key 由 chat 层从该轮回答的检索证据（troubleshooting/case 文档的
  product_model + fault_type）派生并写入 query_log，跨轮次可追溯；
- 状态落在 SQLite fault_progress 表，重启不丢，旧会话无记录时自然不触发。

阈值语义：同一 fault_key 累计 >= FAILED_ATTEMPT_THRESHOLD 次即视为
"连续排查失败"，chat 层据此为下一轮注入 prior_troubleshoot_failed=True。
"""
# 导入 logging，用于记录计数过程
import logging
# 导入 Path，用于确保数据库目录存在
from pathlib import Path
# 导入 datetime 与 timezone，用于更新时间戳
from datetime import datetime, timezone

# 导入 aiosqlite，异步操作 SQLite
import aiosqlite

# 复用 ConversationStore 的重试装饰器与连接配置（同一 db 文件、同一并发场景）
from app.services.conversation_store import _db_retry, _configure_db
# 导入查询日志存储类型（仅用于类型提示与文档说明）
from app.services.query_log_service import QueryLogStore

# 获取当前模块日志器
logger = logging.getLogger(__name__)

# 触发"连续排查失败"的累计次数阈值
FAILED_ATTEMPT_THRESHOLD = 2

# fault_progress 建表 SQL（幂等）
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fault_progress (
    conversation_id TEXT NOT NULL,
    fault_key TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (conversation_id, fault_key)
);
"""

# "已按步骤执行"确认词：命中其一视为用户确认执行过排查步骤
_CONFIRM_WORDS = (
    "按步骤", "按照步骤", "照做", "照着做", "试过", "试了", "尝试过",
    "做了", "操作了", "执行了", "重新校准", "校准过", "校准了",
    "重启过", "重启了", "重置过", "重新对频", "对频了",
)
# "仍无效"信号词：命中其一视为排查无效
_INEFFECTIVE_WORDS = (
    "无效", "没用", "没有用", "不管用", "不行", "还是不行", "依然",
    "没解决", "未解决", "没好", "依旧", "仍然", "没效果", "没有效果",
    "没变化", "还是出现", "还是无法", "还是不能", "还是报", "还是飘", "还是断",
)


# 定义判断用户消息是否为"确认执行且仍无效"的函数
def is_confirmed_ineffective(message: str) -> bool:
    """消息同时命中确认词与无效词才算一次有效失败计数信号。

    只匹配"无效反馈"不匹配"确认执行"（或反之）不计入，避免把普通
    追问、新问题描述误判为排查失败。
    """
    if not message:                                     # 空消息
        return False                                    # 不计数
    confirmed = any(w in message for w in _CONFIRM_WORDS)        # 确认执行信号
    ineffective = any(w in message for w in _INEFFECTIVE_WORDS)  # 无效信号
    return confirmed and ineffective                    # 两者同时命中才计数


# 定义排查失败计数存储类
class FaultProgressStore:
    """fault_progress 表的访问层（与 query_log 共享同一 SQLite 文件）。"""

    # 初始化：保存数据库路径
    def __init__(self, db_path: str):
        self.db_path = db_path                          # 数据库文件路径
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)  # 确保父目录存在

    # 初始化：建表（幂等），在 lifespan 中调用一次
    async def init(self):
        """建表（幂等）。在 lifespan 中调用一次。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            await db.execute("PRAGMA journal_mode = WAL")  # 启用 WAL 日志模式
            await db.executescript(SCHEMA_SQL)           # 执行建表脚本
            await db.commit()                            # 提交

    # 累加指定故障的失败次数
    @_db_retry
    async def increment(self, conversation_id: str, fault_key: str) -> int:
        """对 (conversation_id, fault_key) 的失败计数 +1，返回累加后的值。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            await db.execute(                            # UPSERT 累加
                """INSERT INTO fault_progress (conversation_id, fault_key, failed_attempts, updated_at)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(conversation_id, fault_key)
                   DO UPDATE SET failed_attempts = failed_attempts + 1, updated_at = excluded.updated_at""",
                (conversation_id, fault_key, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()                            # 提交
            cursor = await db.execute(                   # 读回累加后的计数
                "SELECT failed_attempts FROM fault_progress WHERE conversation_id = ? AND fault_key = ?",
                (conversation_id, fault_key),
            )
            row = await cursor.fetchone()                # 取一行
            attempts = int(row[0]) if row else 0         # 计数值
            logger.info(                                 # 记录计数过程（诊断用）
                "fault_progress +1: conv=%s fault_key=%s attempts=%d",
                conversation_id, fault_key, attempts,
            )
            return attempts                              # 返回累加后的计数

    # 记录一次"确认执行仍无效"（chat 层在收到用户消息时调用）
    async def record_confirmation(
        self, query_log_store: QueryLogStore | None, conversation_id: str, user_message: str
    ) -> bool:
        """若用户消息命中"确认执行+仍无效"，对最近一条带 fault_key 的回答累加计数。

        query_log_store 为 None（测试环境未初始化）时跳过。
        返回是否实际累加。
        """
        if not is_confirmed_ineffective(user_message):   # 消息未命中确认+无效模式
            return False                                 # 不计数
        if query_log_store is None:                      # 日志存储未初始化
            logger.warning("query_log_store 未初始化，跳过排查失败计数")  # 告警
            return False                                 # 不计数
        latest = await query_log_store.get_latest_fault_key(conversation_id)  # 最近带 fault_key 的回答
        if not latest or not latest.get("fault_key"):    # 上一轮没有可归属的故障标识
            logger.info("排查失败信号命中但无 fault_key 可归属，跳过计数: conv=%s", conversation_id)  # 记录
            return False                                 # 不计数
        await self.increment(conversation_id, str(latest["fault_key"]))  # 累加该故障计数
        return True                                      # 已累加

    # 判断会话是否存在"连续排查失败"的故障
    @_db_retry
    async def has_repeated_failure(
        self, conversation_id: str, threshold: int = FAILED_ATTEMPT_THRESHOLD
    ) -> bool:
        """会话内任一 fault_key 的失败次数达到阈值即返回 True。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            cursor = await db.execute(                   # 查是否存在达到阈值的故障
                "SELECT 1 FROM fault_progress WHERE conversation_id = ? AND failed_attempts >= ? LIMIT 1",
                (conversation_id, threshold),
            )
            row = await cursor.fetchone()                # 取一行
            return row is not None                       # 命中返回 True

    # 读取会话内全部故障计数（诊断用）
    @_db_retry
    async def list_progress(self, conversation_id: str) -> list[dict]:
        """按失败次数倒序返回会话内全部故障计数（诊断用）。"""
        async with aiosqlite.connect(self.db_path) as db:  # 打开连接
            await _configure_db(db)                      # 应用连接级配置
            db.row_factory = aiosqlite.Row               # 行以字典式 Row 返回
            cursor = await db.execute(                   # 查询该会话全部计数
                "SELECT fault_key, failed_attempts, updated_at FROM fault_progress "
                "WHERE conversation_id = ? ORDER BY failed_attempts DESC",
                (conversation_id,),
            )
            rows = await cursor.fetchall()               # 取结果
            return [dict(r) for r in rows]               # 转字典列表
