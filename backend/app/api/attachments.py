"""Temporary attachment API for the current conversation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile

from app.api.conversations import get_store as get_conversation_store
from app.models.schemas import AttachmentResponse
from app.services.attachment_security import AttachmentValidationError
from app.services.attachment_store import AttachmentStore
from app.services.conversation_store import ConversationStore
from app.api.dependencies import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["attachments"])
# Conversation ownership is checked through the authenticated user's id before
# every attachment operation; attachment rows remain scoped by conversation id.
_store: AttachmentStore | None = None


def set_store(store: AttachmentStore) -> None:
    global _store
    _store = store


def get_store() -> AttachmentStore:
    if _store is None:
        raise RuntimeError("AttachmentStore not initialized")
    return _store


def _response(record) -> AttachmentResponse:
    return AttachmentResponse(
        id=record.id,
        attachment_id=record.id,
        original_name=record.original_name,
        extension=record.extension,
        declared_mime=record.declared_mime,
        detected_mime=record.detected_mime,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        status=record.status,
        extraction_status=record.extraction_status,
        extracted_chars=record.extracted_chars,
        extraction_error=record.extraction_error,
        # Extraction errors are persisted as bounded error codes.  Keep the
        # public field name stable for clients without exposing stack traces.
        extraction_error_code=record.extraction_error,
        extraction_summary=record.extraction_summary,
        scan_status=record.scan_status,
        created_at=record.created_at,
        expires_at=record.expires_at,
        deleted_at=record.deleted_at,
    )


async def _require_conversation(conversation_id: str, store: ConversationStore, user):
    owner_id = getattr(user, "id", None)
    conversation = await store.get_conversation(conversation_id, owner_id) if owner_id else await store.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


async def _read_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Read one multipart part with a hard upper bound."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(min(1024 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise AttachmentValidationError("file_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/{conversation_id}/attachments", response_model=dict, status_code=201)
async def upload_attachments(
    conversation_id: str,
    request: Request,
    store: AttachmentStore = Depends(get_store),
    conversation_store: ConversationStore = Depends(get_conversation_store),
    user=Depends(get_current_user),
):
    """Upload and extract temporary files; no file bytes are returned."""
    await _require_conversation(conversation_id, conversation_store, user)
    try:
        form = await request.form(
            max_files=store.max_files_per_upload,
            max_fields=20,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="multipart_form_invalid")
    uploads = []
    # ``files`` is the documented repeated field; accept common singular
    # aliases so clients do not need a special one-file code path.
    for field_name in ("files", "file", "attachments"):
        uploads.extend(item for item in form.getlist(field_name) if isinstance(item, UploadFile))
    if not uploads:
        raise HTTPException(status_code=400, detail="no_files")
    if len(uploads) > store.max_files_per_upload:
        raise HTTPException(status_code=400, detail="file_count_exceeded")

    payloads: list[tuple[str, bytes, str | None]] = []
    total_bytes = 0
    try:
        for upload in uploads:
            payload = await _read_upload(upload, store.max_file_bytes)
            total_bytes += len(payload)
            if total_bytes > store.max_upload_bytes:
                raise AttachmentValidationError("upload_too_large")
            payloads.append((
                upload.filename or "",
                payload,
                upload.content_type,
            ))
        records = await store.create_attachments(conversation_id, payloads)
        for record in records:
            # AttachmentStore owns the controlled read and metadata update.
            result = await store.extract_attachment(conversation_id, record.id)
            if result is not None and result.extraction_status != "ready":
                # Keep a bounded failed metadata row while removing raw bytes.
                await store.mark_failed(conversation_id, record.id)
        refreshed = [await store.get_attachment(conversation_id, record.id) for record in records]
        public = [_response(record) for record in refreshed if record is not None]
        return {
            "attachments": public,
            "count": len(public),
            "total_size_bytes": sum(item.size_bytes for item in public),
            "total_extracted_chars": sum(item.extracted_chars or 0 for item in public),
        }
    except AttachmentValidationError as exc:
        # create_attachments removes any files written before a batch failure.
        raise HTTPException(status_code=400, detail=exc.code)
    except Exception:
        # A failure after storage creation must not leave bytes behind.
        for record in locals().get("records", []):
            try:
                await store.mark_failed(conversation_id, record.id)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail="attachment_upload_failed")
    finally:
        for upload in uploads:
            try:
                await upload.close()
            except Exception:
                pass


@router.get("/{conversation_id}/attachments", response_model=list[AttachmentResponse])
async def list_attachments(
    conversation_id: str,
    store: AttachmentStore = Depends(get_store),
    conversation_store: ConversationStore = Depends(get_conversation_store),
    user=Depends(get_current_user),
):
    await _require_conversation(conversation_id, conversation_store, user)
    return [_response(record) for record in await store.get_attachments(conversation_id)]


@router.get("/{conversation_id}/attachments/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(
    conversation_id: str,
    attachment_id: str,
    store: AttachmentStore = Depends(get_store),
    conversation_store: ConversationStore = Depends(get_conversation_store),
    user=Depends(get_current_user),
):
    await _require_conversation(conversation_id, conversation_store, user)
    record = await store.get_attachment(conversation_id, attachment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="附件不存在")
    return _response(record)


@router.delete("/{conversation_id}/attachments/{attachment_id}")
async def delete_attachment(
    conversation_id: str,
    attachment_id: str,
    store: AttachmentStore = Depends(get_store),
    conversation_store: ConversationStore = Depends(get_conversation_store),
    user=Depends(get_current_user),
):
    await _require_conversation(conversation_id, conversation_store, user)
    if not await store.delete_attachment(conversation_id, attachment_id):
        raise HTTPException(status_code=404, detail="附件不存在")
    return {"success": True}
