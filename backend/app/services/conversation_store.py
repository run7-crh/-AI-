import aiosqlite
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Optional

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
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
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
"""


class ConversationStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()

    async def create_conversation(self, title: Optional[str] = None) -> str:
        conv_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conv_id, title or "新会话", now, now),
            )
            await db.commit()
        return conv_id

    async def list_conversations(self) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_conversation(self, conv_id: str) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,))
            conv = await cursor.fetchone()
            if not conv:
                return None
            cursor = await db.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conv_id,),
            )
            messages = await cursor.fetchall()
            result = dict(conv)
            result["messages"] = [dict(m) for m in messages]
            for m in result["messages"]:
                if m.get("sources"):
                    m["sources"] = json.loads(m["sources"])
                if m.get("judge_log"):
                    m["judge_log"] = json.loads(m["judge_log"])
            return result

    async def add_message(self, conv_id, role, content, route_path=None,
                          sources=None, judge_log=None) -> str:
        msg_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO messages
                   (id, conversation_id, role, content, route_path, sources, judge_log, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, conv_id, role, content, route_path,
                 json.dumps(sources) if sources else None,
                 json.dumps(judge_log) if judge_log else None, now),
            )
            await db.execute(
                "UPDATE conversations SET updated_at = ?, message_count = message_count + 1 WHERE id = ?",
                (now, conv_id),
            )
            await db.commit()
        return msg_id

    async def delete_conversation(self, conv_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            cursor = await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            await db.commit()
            return cursor.rowcount > 0

    async def update_conversation_title(self, conv_id, title) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conv_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_history(self, conv_id: str, limit: int = 10) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
                (conv_id, limit),
            )
            rows = await cursor.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
