import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user, require_admin, set_auth_store
from app.services.auth_store import AuthStore


@pytest.fixture
def auth_app(tmp_path):
    store = AuthStore(str(tmp_path / "auth.db"))
    app = FastAPI()
    app.get("/me")(lambda user=__import__("fastapi").Depends(get_current_user): user)
    app.get("/admin")(lambda user=__import__("fastapi").Depends(require_admin): user)
    set_auth_store(store)
    return app, store


@pytest.mark.asyncio
async def test_dependencies_reject_missing_and_allow_admin(tmp_path):
    store = AuthStore(str(tmp_path / "auth.db"))
    await store.init(admin_username="root", admin_password="Admin-pass-1")
    set_auth_store(store)
    app = FastAPI()
    from fastapi import Depends
    app.get("/me")(lambda user=Depends(get_current_user): user)
    app.get("/admin")(lambda user=Depends(require_admin): user)
    token = await store.create_session((await store.authenticate("root", "Admin-pass-1")).id)
    with TestClient(app) as client:
        assert client.get("/me").status_code == 401
        assert client.get("/admin", cookies={"agent_session": token}).status_code == 200


@pytest.mark.asyncio
async def test_require_admin_rejects_regular_user(tmp_path):
    store = AuthStore(str(tmp_path / "auth.db"))
    await store.init(admin_username="root", admin_password="Admin-pass-1")
    user = await store.register("regular", "User-pass-1")
    token = await store.create_session(user.id)
    set_auth_store(store)
    app = FastAPI()
    from fastapi import Depends
    app.get("/admin")(lambda user=Depends(require_admin): user)
    with TestClient(app) as client:
        response = client.get("/admin", cookies={"agent_session": token})
    assert response.status_code == 403
    assert response.json()["detail"] == "需要管理员权限"
