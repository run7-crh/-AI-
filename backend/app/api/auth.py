from fastapi import APIRouter, Cookie, Depends, Response, HTTPException, status

from app.config import settings
from app.models.auth import Credentials, UserPublic
from app.api.dependencies import get_auth_store, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.AUTH_COOKIE_SECURE,
    )


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(credentials: Credentials, response: Response):
    store = get_auth_store()
    try:
        user = await store.register(credentials.username, credentials.password)
    except ValueError as exc:
        if str(exc) == "username_taken":
            raise HTTPException(status_code=409, detail="用户名已存在")
        raise HTTPException(status_code=422, detail=str(exc))
    token = await store.create_session(user.id)
    _set_session_cookie(response, token)
    return user


@router.post("/login", response_model=UserPublic)
async def login(credentials: Credentials, response: Response):
    store = get_auth_store()
    user = await store.authenticate(credentials.username, credentials.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = await store.create_session(user.id)
    _set_session_cookie(response, token)
    return user


@router.post("/logout")
async def logout(
    response: Response,
    token: str | None = Cookie(default=None, alias=settings.AUTH_COOKIE_NAME),
):
    if token:
        await get_auth_store().delete_session(token)
    response.delete_cookie(key=settings.AUTH_COOKIE_NAME, samesite="lax", secure=settings.AUTH_COOKIE_SECURE)
    return {"success": True}


@router.get("/me", response_model=UserPublic)
async def me(user: UserPublic = Depends(get_current_user)):
    return user
