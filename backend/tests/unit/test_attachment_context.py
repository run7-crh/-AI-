from datetime import datetime, timedelta, timezone

import pytest

from app.services.attachment_security import AttachmentValidationError
from app.services.attachment_store import AttachmentStore, LocalAttachmentStorage
from app.services.conversation_store import ConversationStore


@pytest.fixture
async def context_store(tmp_path):
    db_path = str(tmp_path / "context.db")
    conversations = ConversationStore(db_path)
    await conversations.init()
    conversation_id = await conversations.create_conversation()
    storage = LocalAttachmentStorage(tmp_path / "attachments")
    store = AttachmentStore(db_path, storage=storage, max_context_chars=20)
    return store, conversations, conversation_id, storage


@pytest.mark.asyncio
async def test_explicit_attachment_context_is_transient_and_evidenced(context_store):
    store, _, conversation_id, _ = context_store
    record = await store.create_attachment(conversation_id, "notes.txt", b"hello", "text/plain")
    await store.extract_attachment(conversation_id, record.id)
    bundle = await store.prepare_chat_attachments(conversation_id, [record.id])
    assert "不受信任" in bundle["attachment_context"]
    evidence = bundle["attachment_evidence"][0]
    assert evidence["source_type"] == "attachment"
    assert evidence["data_type"] == "user_upload"
    assert evidence["document_id"] == f"attachment:{record.id}"
    assert evidence["source_id"] == f"ATTACHMENT:{record.id}"
    assert evidence["product_model"] is None


@pytest.mark.asyncio
async def test_unselected_attachment_is_not_in_context(context_store):
    store, _, conversation_id, _ = context_store
    record = await store.create_attachment(conversation_id, "notes.txt", b"secret", "text/plain")
    bundle = await store.prepare_chat_attachments(conversation_id, [])
    assert bundle["attachment_evidence"] == []
    assert "secret" not in bundle["attachment_context"]
    assert await store.get_attachment(conversation_id, record.id) is not None


@pytest.mark.asyncio
async def test_cross_conversation_and_deleted_attachment_are_rejected(context_store):
    store, conversations, conversation_id, _ = context_store
    other = await conversations.create_conversation()
    record = await store.create_attachment(conversation_id, "notes.txt", b"hello", "text/plain")
    with pytest.raises(AttachmentValidationError, match="not_found"):
        await store.prepare_chat_attachments(other, [record.id])
    await store.delete_attachment(conversation_id, record.id)
    with pytest.raises(AttachmentValidationError, match="not_found"):
        await store.prepare_chat_attachments(conversation_id, [record.id])


@pytest.mark.asyncio
async def test_expired_and_failed_attachment_are_rejected(context_store):
    store, _, conversation_id, _ = context_store
    record = await store.create_attachment(conversation_id, "notes.txt", b"hello", "text/plain")
    async with store._db_module().connect(store.db_path) as db:
        await db.execute("UPDATE attachments SET expires_at = ? WHERE id = ?", ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), record.id))
        await db.commit()
    with pytest.raises(AttachmentValidationError, match="not_ready|expired"):
        await store.prepare_chat_attachments(conversation_id, [record.id])


@pytest.mark.asyncio
async def test_failed_attachment_is_rejected(context_store):
    store, _, conversation_id, _ = context_store
    record = await store.create_attachment(conversation_id, "notes.txt", b"hello", "text/plain")
    await store.extract_attachment(conversation_id, record.id)
    await store.update_extraction_result(
        conversation_id,
        record.id,
        status="failed",
        extracted_chars=0,
        error="extraction_failed",
        summary="附件文本抽取未完成",
    )
    with pytest.raises(AttachmentValidationError, match="unavailable"):
        await store.prepare_chat_attachments(conversation_id, [record.id])
