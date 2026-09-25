import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from app.services.attachment_security import (
    AttachmentValidationError,
    validate_attachment_bytes,
    validate_filename,
)
from app.services.attachment_store import AttachmentStore, LocalAttachmentStorage
from app.services.conversation_store import ConversationStore
from app.services.ticket_store import TicketStore


@pytest.fixture
async def attachment_store(tmp_path):
    db_path = str(tmp_path / "attachments.db")
    conversations = ConversationStore(db_path)
    await conversations.init()
    storage = LocalAttachmentStorage(tmp_path / "attachments")
    store = AttachmentStore(
        db_path,
        storage=storage,
        max_file_bytes=8,
        max_files_per_upload=2,
        max_session_bytes=12,
    )
    conversation_id = await conversations.create_conversation()
    yield store, conversations, conversation_id, storage


def test_allowed_extensions_and_rejected_names():
    for name in ("manual.pdf", "notes.txt", "readme.md", "flight.log", "data.json", "data.csv", "manual.docx"):
        assert validate_filename(name).extension in {".pdf", ".txt", ".md", ".log", ".json", ".csv", ".docx"}

    for name in ("script.exe", "report.txt.pdf", "../manual.pdf", "folder\\manual.pdf", "bad\x00.pdf", "bad\n.pdf"):
        with pytest.raises(AttachmentValidationError):
            validate_filename(name)


def test_signature_and_declared_mime_are_checked():
    with pytest.raises(AttachmentValidationError, match="mime"):
        validate_attachment_bytes("manual.pdf", b"%PDF-1.7", "text/plain")
    with pytest.raises(AttachmentValidationError, match="signature"):
        validate_attachment_bytes("manual.pdf", b"plain text", "application/pdf")
    result = validate_attachment_bytes("manual.pdf", b"%PDF-1.7\nbody\n%%EOF", "application/pdf")
    assert result.detected_mime == "application/pdf"


def test_sha256_is_stable_and_size_is_enforced():
    payload = b"12345678"
    result = validate_attachment_bytes("notes.txt", payload, "text/plain", max_file_bytes=8)
    assert result.size_bytes == 8
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    with pytest.raises(AttachmentValidationError, match="too_large"):
        validate_attachment_bytes("notes.txt", payload + b"9", "text/plain", max_file_bytes=8)


@pytest.mark.asyncio
async def test_attachment_is_owned_by_conversation_and_deleted(attachment_store):
    store, conversations, conversation_id, storage = attachment_store
    other_conversation_id = await conversations.create_conversation()
    record = await store.create_attachment(conversation_id, "notes.txt", b"hello", "text/plain")
    assert record.status == "ready"
    assert await store.get_attachment(other_conversation_id, record.id) is None
    assert await store.delete_attachment(other_conversation_id, record.id) is False
    assert await store.delete_attachment(conversation_id, record.id) is True
    deleted = await store.get_attachment(conversation_id, record.id, include_deleted=True)
    assert deleted is not None and deleted.status == "deleted"
    assert not storage.exists(record.storage_key)


@pytest.mark.asyncio
async def test_expired_cleanup_removes_file_and_marks_record(attachment_store):
    store, _, conversation_id, storage = attachment_store
    record = await store.create_attachment(conversation_id, "notes.txt", b"hello", "text/plain")
    count = await store.cleanup_expired(now="9999-01-01T00:00:00+00:00")
    assert count == 1
    expired = await store.get_attachment(conversation_id, record.id, include_deleted=True)
    assert expired is not None and expired.status == "expired"
    assert not storage.exists(record.storage_key)


@pytest.mark.asyncio
async def test_promoted_ticket_evidence_survives_cleanup(attachment_store):
    store, conversations, conversation_id, storage = attachment_store
    tickets = TicketStore(store.db_path)
    await tickets.init()
    record = await store.create_attachment(conversation_id, "flight.log", b"LOG\n", "text/plain")
    ticket = await tickets.create_ticket({
        "user_id": "user-1",
        "conversation_id": conversation_id,
        "title": "遥控器无法连接",
        "problem_summary": "用户反馈遥控器无法连接飞机。",
        "priority": "normal",
        "safety_level": "none",
        "status": "draft",
    })
    retention_until = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    linked = await store.promote_to_ticket(
        conversation_id, [record.id], ticket["id"], retention_until=retention_until
    )
    assert linked == [record.id]
    evidence = await tickets.list_evidence(ticket["id"])
    assert [(item["evidence_type"], item["evidence_id"]) for item in evidence] == [
        ("attachment", record.id)
    ]
    promoted = await store.get_attachment(conversation_id, record.id)
    assert promoted.expires_at > datetime.now(timezone.utc) + timedelta(days=29)

    removed = await store.cleanup_expired(now="9999-01-01T00:00:00+00:00")
    assert removed == 0
    kept = await store.get_attachment(conversation_id, record.id)
    assert kept is not None and kept.status == "ready"
    assert storage.exists(record.storage_key)
    # Duplicate promotion is absorbed by the evidence unique constraint.
    linked_again = await store.promote_to_ticket(
        conversation_id, [record.id], ticket["id"], retention_until=retention_until
    )
    assert linked_again == [record.id]
    assert len(await tickets.list_evidence(ticket["id"])) == 1


@pytest.mark.asyncio
async def test_promote_rejects_foreign_and_non_ready_attachments(attachment_store):
    store, conversations, conversation_id, _ = attachment_store
    tickets = TicketStore(store.db_path)
    await tickets.init()
    ticket = await tickets.create_ticket({
        "user_id": "user-1",
        "conversation_id": conversation_id,
        "title": "遥控器无法连接",
        "problem_summary": "用户反馈遥控器无法连接飞机。",
        "priority": "normal",
        "safety_level": "none",
        "status": "draft",
    })
    other_conversation_id = await conversations.create_conversation()
    foreign = await store.create_attachment(
        other_conversation_id, "other.log", b"OTHER\n", "text/plain"
    )
    with pytest.raises(AttachmentValidationError, match="attachment_not_found"):
        await store.promote_to_ticket(
            conversation_id,
            [foreign.id],
            ticket["id"],
            retention_until="9999-01-01T00:00:00+00:00",
        )
    own = await store.create_attachment(conversation_id, "own.log", b"OWN\n", "text/plain")
    await store.delete_attachment(conversation_id, own.id)
    with pytest.raises(AttachmentValidationError, match="attachment_not_ready"):
        await store.promote_to_ticket(
            conversation_id,
            [own.id],
            ticket["id"],
            retention_until="9999-01-01T00:00:00+00:00",
        )
    assert await store.promote_to_ticket(
        conversation_id, [], ticket["id"], retention_until="9999-01-01T00:00:00+00:00"
    ) == []


@pytest.mark.asyncio
async def test_failed_cleanup_removes_file_and_marks_failed(attachment_store):
    store, _, conversation_id, storage = attachment_store
    record = await store.create_attachment(conversation_id, "notes.txt", b"hello", "text/plain")
    assert await store.mark_failed(conversation_id, record.id) is True
    failed = await store.get_attachment(conversation_id, record.id, include_deleted=True)
    assert failed is not None and failed.status == "failed"
    assert not storage.exists(record.storage_key)


@pytest.mark.asyncio
async def test_conversation_cleanup_removes_all_owned_files(attachment_store):
    store, _, conversation_id, storage = attachment_store
    records = await store.create_attachments(
        conversation_id,
        [("a.txt", b"one", "text/plain"), ("b.txt", b"two", "text/plain")],
    )
    assert await store.delete_conversation_attachments(conversation_id) == 2
    assert not any(storage.exists(record.storage_key) for record in records)


@pytest.mark.asyncio
async def test_session_size_limit_and_message_link(attachment_store):
    store, conversations, conversation_id, _ = attachment_store
    await store.create_attachment(conversation_id, "a.txt", b"12345678", "text/plain")
    with pytest.raises(AttachmentValidationError, match="session_too_large"):
        await store.create_attachment(conversation_id, "b.txt", b"12345", "text/plain")
    message_id = await conversations.add_message(conversation_id, "user", "附件")
    record = await store.get_attachments(conversation_id)
    assert len(record) == 1
    assert await store.link_message_attachment(conversation_id, message_id, record[0].id) is True
    linked = await store.list_message_attachments(conversation_id, message_id)
    assert [item.id for item in linked] == [record[0].id]


@pytest.mark.asyncio
async def test_batch_failure_cleans_up_files_created_by_same_batch(attachment_store):
    store, _, conversation_id, storage = attachment_store
    await store.create_attachment(conversation_id, "a.txt", b"12345678", "text/plain")
    with pytest.raises(AttachmentValidationError, match="session_too_large"):
        await store.create_attachments(
            conversation_id,
            [("b.txt", b"123", "text/plain"), ("c.txt", b"123", "text/plain")],
        )
    assert len(await store.get_attachments(conversation_id)) == 1
    assert len([path for path in Path(storage.base_dir).iterdir() if path.is_dir()]) == 1


@pytest.mark.asyncio
async def test_old_database_migration_creates_attachment_tables(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(
            """
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                message_count INTEGER DEFAULT 0
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL,
                route_path TEXT, sources TEXT, judge_log TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        await db.commit()
    await ConversationStore(db_path).init()
    async with aiosqlite.connect(db_path) as db:
        tables = {
            row[0]
            for row in await (await db.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        }
        columns = {row[1] for row in await (await db.execute("PRAGMA table_info(attachments)")).fetchall()}
    assert {"attachments", "message_attachments"} <= tables
    assert "content" not in columns


@pytest.mark.asyncio
async def test_conversation_history_includes_attachment_summary_without_payload(tmp_path):
    db_path = str(tmp_path / "history.db")
    conversations = ConversationStore(db_path)
    await conversations.init()
    storage = LocalAttachmentStorage(tmp_path / "attachments")
    attachments = AttachmentStore(db_path, storage=storage)
    await attachments.init()
    conversation_id = await conversations.create_conversation()
    record = await attachments.create_attachment(conversation_id, "flight.log", b"private body", "text/plain")
    await attachments.extract_attachment(conversation_id, record.id)
    message_id = await conversations.add_message(conversation_id, "user", "请看附件")
    assert await attachments.link_message_attachment(conversation_id, message_id, record.id)

    detail = await conversations.get_conversation(conversation_id)
    summary = detail["messages"][0]["attachments"][0]
    assert summary["id"] == record.id
    assert summary["original_name"] == "flight.log"
    assert summary["status"] == "ready"
    assert "content" not in summary
    assert "storage_key" not in summary
    assert "private body" not in str(summary)
