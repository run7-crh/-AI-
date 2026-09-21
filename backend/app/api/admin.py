from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.dependencies import get_auth_store, require_admin
from app.config import resolve_kb_profile, settings
from app.models.auth import Credentials, UserPublic
from app.models.feedback import FeedbackStats
from app.services.knowledge_base_import import ImportValidationError, KnowledgeBaseImportService
from app.services.log_reader import LogReader

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ActiveUpdate(BaseModel):
    is_active: bool


class PasswordUpdate(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


async def _find_user(user_id: str):
    return await get_auth_store().get_user(user_id)


@router.get("/users", response_model=list[UserPublic])
async def list_users(_admin: UserPublic = Depends(require_admin)):
    return await get_auth_store().list_users()


@router.post("/users", response_model=UserPublic, status_code=201)
async def create_user(body: Credentials, _admin: UserPublic = Depends(require_admin)):
    try:
        return await get_auth_store().register(body.username, body.password)
    except ValueError as exc:
        if str(exc) == "username_taken":
            raise HTTPException(status_code=409, detail="用户名已存在")
        if str(exc) == "invalid_password":
            raise HTTPException(status_code=422, detail="密码长度不符合要求")
        raise HTTPException(status_code=422, detail=str(exc))


async def _set_user_active(user_id: str, body: ActiveUpdate):
    store = get_auth_store()
    target = await _find_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.role == "admin" and target.is_active and not body.is_active and await store.count_active_admins() <= 1:
        raise HTTPException(status_code=409, detail="不能停用最后一个管理员")
    await store.set_active(user_id, body.is_active)
    return await _find_user(user_id)


@router.patch("/users/{user_id}/status", response_model=UserPublic)
@router.patch("/users/{user_id}/active", response_model=UserPublic, include_in_schema=False)
async def set_user_active(user_id: str, body: ActiveUpdate, _admin: UserPublic = Depends(require_admin)):
    return await _set_user_active(user_id, body)


@router.post("/users/{user_id}/password")
async def reset_user_password(user_id: str, body: PasswordUpdate, _admin: UserPublic = Depends(require_admin)):
    store = get_auth_store()
    if await _find_user(user_id) is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        await store.reset_password(user_id, body.password)
    except ValueError:
        raise HTTPException(status_code=422, detail="密码长度不符合要求")
    return {"ok": True}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, _admin: UserPublic = Depends(require_admin)):
    store = get_auth_store()
    target = await _find_user(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.role == "admin" and target.is_active and await store.count_active_admins() <= 1:
        raise HTTPException(status_code=409, detail="不能删除最后一个管理员")

    from app.main import get_attachment_store, get_query_log_store, get_store

    conversation_store = get_store()
    for conversation in await conversation_store.list_conversations(user_id):
        attachment_store = get_attachment_store()
        if attachment_store is not None:
            await attachment_store.delete_conversation_attachments(conversation["id"])
        await conversation_store.delete_conversation(conversation["id"], user_id)
    query_log_store = get_query_log_store()
    if query_log_store is not None:
        await query_log_store.delete_by_user(user_id)
    await store.delete_user(user_id)


@router.get("/feedback/stats", response_model=FeedbackStats)
async def feedback_stats(_admin: UserPublic = Depends(require_admin)):
    from app.main import get_feedback_store
    return FeedbackStats(**(await get_feedback_store().get_stats()))


@router.get("/logs")
async def read_logs(limit: int = 100, max_line_length: int = 4000, _admin: UserPublic = Depends(require_admin)):
    return {"lines": LogReader(settings.LOG_DIR).read(limit=limit, max_line_length=max_line_length)}


@router.post("/knowledge-base/import")
async def import_knowledge_base(files: list[UploadFile] = File(...), _admin: UserPublic = Depends(require_admin)):
    service = KnowledgeBaseImportService(
        resolve_kb_profile().data_dir,
        max_file_bytes=settings.KB_IMPORT_MAX_FILE_BYTES,
        max_files=settings.KB_IMPORT_MAX_FILES,
    )
    try:
        names = service.import_files([(upload.filename or "", await upload.read()) for upload in files])
    except ImportValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.code)
    return {"count": len(names), "files": names}
