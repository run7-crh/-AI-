"""Attachment records and SQLite schema for temporary user uploads.

Attachments are deliberately separate from messages and query logs.  The
payload lives in a pluggable storage backend; SQLite stores only metadata and
relationships.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


AttachmentStatus = Literal["pending", "ready", "failed", "expired", "deleted"]
ExtractionStatus = Literal["pending", "ready", "failed", "skipped"]
ScanStatus = Literal["pending", "clean", "suspicious", "failed", "not_run"]


ATTACHMENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    original_name TEXT NOT NULL,
    extension TEXT NOT NULL,
    declared_mime TEXT,
    detected_mime TEXT,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    extracted_chars INTEGER,
    extraction_error TEXT,
    extraction_summary TEXT,
    scan_status TEXT NOT NULL DEFAULT 'not_run',
    storage_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    deleted_at TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_attachments_conversation
    ON attachments(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attachments_expiry
    ON attachments(status, expires_at);

CREATE TABLE IF NOT EXISTS message_attachments (
    message_id TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (message_id, attachment_id),
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (attachment_id) REFERENCES attachments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_message_attachments_attachment
    ON message_attachments(attachment_id);
"""


@dataclass(frozen=True)
class Attachment:
    id: str
    conversation_id: str
    original_name: str
    extension: str
    declared_mime: str | None
    detected_mime: str | None
    size_bytes: int
    sha256: str
    status: AttachmentStatus
    extraction_status: ExtractionStatus
    scan_status: ScanStatus
    storage_key: str
    created_at: datetime
    expires_at: datetime
    deleted_at: datetime | None = None
    extracted_chars: int | None = None
    extraction_error: str | None = None
    extraction_summary: str | None = None


@dataclass(frozen=True)
class MessageAttachment:
    message_id: str
    attachment_id: str
    created_at: datetime
