from fastapi import Cookie, Depends, HTTPException

from app.config import settings
from app.models.auth import UserPublic
from app.services.auth_store import AuthStore

_auth_store: AuthStore | None = None


def set_auth_store(store: AuthStore) -> None:
    global _auth_store
    _auth_store = store


def get_auth_store() -> AuthStore:
    if _auth_store is None:
        raise RuntimeError("AuthStore not initialized")
    return _auth_store


async def get_current_user(
    token: str | None = Cookie(default=None, alias=settings.AUTH_COOKIE_NAME),
) -> UserPublic:
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = await get_auth_store().get_user_by_session(token)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录")
    return user


async def require_admin(user: UserPublic = Depends(get_current_user)) -> UserPublic:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
