"""SQLite persistence for the single-brand after-sales ticket module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import aiosqlite

from app.services.conversation_store import _configure_db, _db_retry


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    ticket_number TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    title TEXT NOT NULL,
    problem_summary TEXT NOT NULL,
    device_model TEXT,
    serial_number TEXT,
    firmware_version TEXT,
    fault_category TEXT,
    priority TEXT NOT NULL,
    safety_level TEXT NOT NULL,
    escalation_reason TEXT,
    assignee_user_id TEXT,
    status TEXT NOT NULL,
    resolution_summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    closed_at TEXT,
    user_confirmed_at TEXT,
    UNIQUE(user_id, conversation_id)
);

CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_assignee ON tickets(assignee_user_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS ticket_events (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    body TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ticket_events_ticket
    ON ticket_events(ticket_id, created_at ASC);

CREATE TABLE IF NOT EXISTS ticket_evidence (
    id TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(ticket_id, evidence_type, evidence_id),
    FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ticket_evidence_ticket
    ON ticket_evidence(ticket_id, created_at ASC);
"""


class TicketStore:
    """Access layer for ticket records, audit events and evidence links."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _ticket_number() -> str:
        return f"T-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8].upper()}"

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            await db.execute("PRAGMA journal_mode = WAL")
            await db.executescript(SCHEMA_SQL)
            await db.commit()

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict:
        result = dict(row)
        if result.get("metadata_json") is not None:
            result["metadata"] = json.loads(result.pop("metadata_json"))
        return result

    @_db_retry
    async def create_ticket(self, payload: dict) -> dict:
        ticket_id = str(uuid4())
        now = self._now()
        ticket_number = self._ticket_number()
        fields = (
            "user_id", "conversation_id", "title", "problem_summary",
            "device_model", "serial_number", "firmware_version", "fault_category",
            "priority", "safety_level", "escalation_reason", "assignee_user_id",
            "status", "resolution_summary",
        )
        values = [payload.get(field) for field in fields]
        if not values[0] or not values[1] or not values[2] or not values[3]:
            raise ValueError("ticket_required_field_missing")
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            try:
                await db.execute(
                    """INSERT INTO tickets
                       (id, ticket_number, user_id, conversation_id, title, problem_summary,
                        device_model, serial_number, firmware_version, fault_category,
                        priority, safety_level, escalation_reason, assignee_user_id,
                        status, resolution_summary, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ticket_id, ticket_number, *values, now, now),
                )
            except aiosqlite.IntegrityError as exc:
                if "tickets.user_id, tickets.conversation_id" in str(exc) or "UNIQUE constraint failed: tickets.user_id" in str(exc):
                    raise ValueError("ticket_conversation_exists") from exc
                raise
            await db.commit()
            return await self._get_by_id(db, ticket_id)

    async def _get_by_id(self, db: aiosqlite.Connection, ticket_id: str, user_id: str | None = None) -> dict | None:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM tickets WHERE id = ?"
        params: list[str] = [ticket_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        row = await (await db.execute(query, params)).fetchone()
        return dict(row) if row else None

    @_db_retry
    async def get_ticket(self, ticket_id: str, user_id: str | None = None) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            return await self._get_by_id(db, ticket_id, user_id)

    @_db_retry
    async def get_by_user_conversation(self, user_id: str, conversation_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM tickets WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            )).fetchone()
            return dict(row) if row else None

    @_db_retry
    async def delete_ticket(self, ticket_id: str) -> bool:
        """Hard-delete a ticket; events and evidence cascade via FK.

        Used only as compensation when post-creation steps (e.g. attachment
        promotion) fail, so a failed draft leaves no orphan rows behind.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            cursor = await db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
            await db.commit()
            return cursor.rowcount > 0

    @_db_retry
    async def list_tickets(self, user_id: str | None = None) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            db.row_factory = aiosqlite.Row
            if user_id is None:
                cursor = await db.execute("SELECT * FROM tickets ORDER BY updated_at DESC, rowid DESC")
            else:
                cursor = await db.execute(
                    "SELECT * FROM tickets WHERE user_id = ? ORDER BY updated_at DESC, rowid DESC",
                    (user_id,),
                )
            return [dict(row) for row in await cursor.fetchall()]

    @_db_retry
    async def append_event(
        self,
        *,
        ticket_id: str,
        actor_type: str,
        actor_id: str | None,
        event_type: str,
        from_status: str | None,
        to_status: str | None,
        body: str | None,
        metadata: dict | None,
        created_at: str | None = None,
    ) -> str:
        event_id = str(uuid4())
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            await db.execute(
                """INSERT INTO ticket_events
                   (id, ticket_id, actor_type, actor_id, event_type, from_status,
                    to_status, body, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, ticket_id, actor_type, actor_id, event_type,
                    from_status, to_status, body,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    created_at or self._now(),
                ),
            )
            await db.commit()
        return event_id

    @_db_retry
    async def apply_transition(
        self,
        ticket_id: str,
        *,
        from_status: str,
        to_status: str,
        fields: dict | None = None,
        event: dict | None = None,
    ) -> dict:
        """Guarded status update plus audit event in one SQLite transaction.

        The UPDATE carries a ``status = from_status`` guard so concurrent
        transitions cannot double-apply: only one wins, the loser raises
        ``ticket_status_conflict``. Column names in ``fields`` must come from
        the service layer's fixed whitelist, never from user input.
        """
        columns = ["status", "updated_at"]
        values: list = [to_status, self._now()]
        for key, value in (fields or {}).items():
            columns.append(key)
            values.append(value)
        set_sql = ", ".join(f"{column} = ?" for column in columns)
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            cursor = await db.execute(
                f"UPDATE tickets SET {set_sql} WHERE id = ? AND status = ?",
                (*values, ticket_id, from_status),
            )
            if cursor.rowcount == 0:
                raise ValueError("ticket_status_conflict")
            payload = event or {}
            await db.execute(
                """INSERT INTO ticket_events
                   (id, ticket_id, actor_type, actor_id, event_type, from_status,
                    to_status, body, metadata_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), ticket_id, payload.get("actor_type", "system"),
                    payload.get("actor_id"), payload.get("event_type", "status_changed"),
                    from_status, to_status, payload.get("body"),
                    json.dumps(payload.get("metadata") or {}, ensure_ascii=False),
                    self._now(),
                ),
            )
            await db.commit()
            return await self._get_by_id(db, ticket_id)

    @_db_retry
    async def list_events(self, ticket_id: str) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                "SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY created_at ASC, rowid ASC",
                (ticket_id,),
            )).fetchall()
            return [self._row_to_dict(row) for row in rows]

    @_db_retry
    async def add_evidence(self, ticket_id: str, evidence_type: str, evidence_id: str) -> str:
        evidence_row_id = str(uuid4())
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            await db.execute(
                """INSERT OR IGNORE INTO ticket_evidence
                   (id, ticket_id, evidence_type, evidence_id, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (evidence_row_id, ticket_id, evidence_type, evidence_id, self._now()),
            )
            await db.commit()
            row = await (await db.execute(
                """SELECT id FROM ticket_evidence
                   WHERE ticket_id = ? AND evidence_type = ? AND evidence_id = ?""",
                (ticket_id, evidence_type, evidence_id),
            )).fetchone()
            return row[0]

    @_db_retry
    async def list_evidence(self, ticket_id: str) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            await _configure_db(db)
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(
                "SELECT * FROM ticket_evidence WHERE ticket_id = ? ORDER BY created_at ASC, rowid ASC",
                (ticket_id,),
            )).fetchall()
            return [dict(row) for row in rows]
