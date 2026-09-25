import io
import json
import zipfile
from datetime import datetime, timezone

import pytest
from starlette.datastructures import FormData, Headers, UploadFile

from app.api.attachments import (
    delete_attachment,
    get_attachment,
    list_attachments,
    upload_attachments,
)
from app.services.attachment_store import AttachmentStore, LocalAttachmentStorage
from app.services.conversation_store import ConversationStore


class FakeRequest:
    def __init__(self, uploads):
        self.uploads = uploads

    async def form(self, **kwargs):
        return FormData([("files", upload) for upload in self.uploads])


def upload(name, payload, mime):
    return UploadFile(io.BytesIO(payload), filename=name, headers=Headers({"content-type": mime}))


def docx_bytes():
    xml = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body></w:document>'
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def pdf_bytes():
    # Valid minimal PDF with an EOF marker; extraction may report no text.
    return b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture
async def api_context(tmp_path):
    db_path = str(tmp_path / "api.db")
    conversations = ConversationStore(db_path)
    await conversations.init()
    first = await conversations.create_conversation()
    second = await conversations.create_conversation()
    storage = LocalAttachmentStorage(tmp_path / "attachments")
    store = AttachmentStore(db_path, storage=storage, max_files_per_upload=10)
    await store.init()
    return store, conversations, first, second, storage


@pytest.mark.asyncio
async def test_upload_accepts_all_seven_formats_without_exposing_storage(api_context):
    store, conversations, conversation_id, _, storage = api_context
    files = [
        upload("a.txt", b"text", "text/plain"),
        upload("a.md", b"# text", "text/markdown"),
        upload("a.log", b"log", "text/plain"),
        upload("a.json", json.dumps({"ok": True}).encode(), "application/json"),
        upload("a.csv", b"a,b\n1,2\n", "text/csv"),
        upload("a.docx", docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        upload("a.pdf", pdf_bytes(), "application/pdf"),
    ]
    response = await upload_attachments(conversation_id, FakeRequest(files), store, conversations)
    records = response["attachments"]
    assert len(records) == 7
    assert all(item.attachment_id.startswith("att_") for item in records)
    assert all("storage_key" not in item.model_fields_set for item in records)
    for item in records:
        if item.status == "ready":
            stored = await store.get_attachment(conversation_id, item.id)
            assert stored is not None and storage.exists(stored.storage_key)


@pytest.mark.asyncio
async def test_attachment_api_enforces_conversation_boundary_and_delete(api_context):
    store, conversations, conversation_id, other_id, _ = api_context
    response = await upload_attachments(
        conversation_id,
        FakeRequest([upload("a.txt", b"hello", "text/plain")]),
        store,
        conversations,
    )
    attachment_id = response["attachments"][0].id
    with pytest.raises(Exception) as error:
        await get_attachment(other_id, attachment_id, store, conversations)
    assert getattr(error.value, "status_code", None) == 404
    assert (await delete_attachment(conversation_id, attachment_id, store, conversations))["success"] is True
    with pytest.raises(Exception) as error:
        await get_attachment(conversation_id, attachment_id, store, conversations)
    assert getattr(error.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_list_attachment_metadata_has_no_full_text(api_context):
    store, conversations, conversation_id, _, _ = api_context
    await upload_attachments(
        conversation_id,
        FakeRequest([upload("a.txt", b"private body", "text/plain")]),
        store,
        conversations,
    )
    listed = await list_attachments(conversation_id, store, conversations)
    assert len(listed) == 1
    assert not hasattr(listed[0], "sanitized_text")


@pytest.mark.asyncio
async def test_upload_rejects_mime_and_size_before_storage(api_context):
    store, conversations, conversation_id, _, storage = api_context
    store.max_file_bytes = 4
    with pytest.raises(Exception) as error:
        await upload_attachments(
            conversation_id,
            FakeRequest([upload("a.txt", b"hello", "application/json")]),
            store,
            conversations,
        )
    assert getattr(error.value, "status_code", None) == 400
    assert list(storage.base_dir.iterdir()) == []
