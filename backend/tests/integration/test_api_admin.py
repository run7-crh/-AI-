import pytest
from httpx import ASGITransport, AsyncClient
from asgi_lifespan import LifespanManager
from app.main import app
from app.config import settings
from types import SimpleNamespace

from app.api import index as index_api


@pytest.fixture
async def client():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_admin_routes_require_admin_and_admin_can_list_users(client):
    normal = await client.post("/api/auth/register", json={"username": "normal", "password": "User-pass-1"})
    assert normal.status_code == 201
    assert (await client.get("/api/admin/users")).status_code == 403
    await client.post("/api/auth/logout")
    admin = await client.post("/api/auth/login", json={"username": "test-admin", "password": "Admin-pass-1"})
    assert admin.status_code == 200
    users = await client.get("/api/admin/users")
    assert users.status_code == 200
    assert all("password_hash" not in user and "session" not in user for user in users.json())


@pytest.mark.asyncio
async def test_normal_user_is_forbidden_from_every_admin_operation(client):
    registered = await client.post("/api/auth/register", json={"username": "normal-all", "password": "User-pass-1"})
    assert registered.status_code == 201
    user_id = registered.json()["id"]
    checks = [
        ("get", "/api/admin/users", None),
        ("post", "/api/admin/users", {"username": "another", "password": "User-pass-2"}),
        ("patch", f"/api/admin/users/{user_id}/status", {"is_active": False}),
        ("patch", f"/api/admin/users/{user_id}/active", {"is_active": False}),
        ("post", f"/api/admin/users/{user_id}/password", {"password": "New-pass-2"}),
        ("delete", f"/api/admin/users/{user_id}", None),
        ("get", "/api/admin/feedback/stats", None),
        ("get", "/api/admin/logs", None),
        ("post", "/api/admin/knowledge-base/import", {"files": ("x.md", b"# x", "text/markdown")}),
        ("post", "/api/index/rebuild", None),
    ]
    for method, path, payload in checks:
        kwargs = {}
        if method in {"post", "patch"} and payload is not None:
            if path.endswith("knowledge-base/import"):
                kwargs["files"] = payload
            else:
                kwargs["json"] = payload
        response = await getattr(client, method)(path, **kwargs)
        assert response.status_code == 403, (method, path, response.text)


@pytest.mark.asyncio
async def test_admin_can_create_user_read_stats_logs_and_rebuild(client, tmp_path, monkeypatch):
    await client.post("/api/auth/login", json={"username": "test-admin", "password": "Admin-pass-1"})
    created = await client.post("/api/admin/users", json={"username": "created-admin-test", "password": "User-pass-1"})
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "user"
    monkeypatch.setattr(settings, "LOG_DIR", str(tmp_path))
    (tmp_path / "app.log").write_text("token=hidden\nadmin-line", encoding="utf-8")
    logs = await client.get("/api/admin/logs", params={"limit": 2, "max_line_length": 80})
    assert logs.status_code == 200
    assert "hidden" not in logs.text
    stats = await client.get("/api/admin/feedback/stats")
    assert stats.status_code == 200
    async def no_graph_build():
        return None
    monkeypatch.setattr(index_api, "build_knowledge_graph", no_graph_build)
    rebuilt = await client.post("/api/index/rebuild")
    assert rebuilt.status_code == 200, rebuilt.text


@pytest.mark.asyncio
async def test_last_admin_cannot_be_disabled_or_deleted(client):
    await client.post("/api/auth/login", json={"username": "test-admin", "password": "Admin-pass-1"})
    admin_id = (await client.get("/api/auth/me")).json()["id"]
    disabled = await client.patch(f"/api/admin/users/{admin_id}/status", json={"is_active": False})
    assert disabled.status_code == 409
    deleted = await client.delete(f"/api/admin/users/{admin_id}")
    assert deleted.status_code == 409
    assert (await client.get("/api/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_disabling_user_invalidates_already_issued_cookie(client):
    registered = await client.post("/api/auth/register", json={"username": "disable-me", "password": "User-pass-1"})
    assert registered.status_code == 201
    user_id = registered.json()["id"]
    old_cookie = client.cookies.get(settings.AUTH_COOKIE_NAME)
    await client.post("/api/auth/logout")
    assert (await client.post("/api/auth/login", json={"username": "test-admin", "password": "Admin-pass-1"})).status_code == 200
    assert (await client.patch(f"/api/admin/users/{user_id}/status", json={"is_active": False})).status_code == 200
    await client.post("/api/auth/logout")
    assert (await client.post("/api/auth/login", json={"username": "disable-me", "password": "User-pass-1"})).status_code == 401
    client.cookies.set(settings.AUTH_COOKIE_NAME, old_cookie)
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_import_uses_profile_directory_and_never_rebuilds(client, tmp_path, monkeypatch):
    await client.post("/api/auth/login", json={"username": "test-admin", "password": "Admin-pass-1"})
    profile = SimpleNamespace(data_dir=tmp_path)
    monkeypatch.setattr("app.api.admin.resolve_kb_profile", lambda: profile)
    response = await client.post(
        "/api/admin/knowledge-base/import",
        files=[("files", ("safe.md", b"# safe", "text/markdown"))],
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"count": 1, "files": ["safe.md"]}
    assert (tmp_path / "safe.md").read_bytes() == b"# safe"


@pytest.mark.asyncio
async def test_admin_can_disable_reset_delete_user_and_import(client, tmp_path, monkeypatch):
    created = await client.post("/api/auth/register", json={"username": "target", "password": "User-pass-1"})
    assert created.status_code == 201
    user_id = created.json()["id"]
    await client.post("/api/auth/logout")
    assert (await client.post("/api/auth/login", json={"username": "test-admin", "password": "Admin-pass-1"})).status_code == 200
    assert (await client.patch(f"/api/admin/users/{user_id}/active", json={"is_active": False})).status_code == 200
    assert (await client.post(f"/api/admin/users/{user_id}/password", json={"password": "New-pass-2"})).status_code == 200
    assert (await client.delete(f"/api/admin/users/{user_id}")).status_code == 204
    assert (await client.post("/api/admin/knowledge-base/import", files={"files": ("guide.md", b"# guide", "text/markdown")})).status_code == 200


@pytest.mark.asyncio
async def test_rebuild_is_admin_protected(client):
    assert (await client.post("/api/index/rebuild")).status_code == 401
