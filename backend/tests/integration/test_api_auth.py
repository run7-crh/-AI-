import pytest
from httpx import ASGITransport, AsyncClient
from asgi_lifespan import LifespanManager

from app.main import app


@pytest.fixture
async def client():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_register_me_logout_and_cookie(client):
    response = await client.post("/api/auth/register", json={"username": "alice", "password": "Alice-pass-1"})
    assert response.status_code == 201
    assert "password_hash" not in response.text and "session" not in response.text
    cookie = response.cookies.get("agent_session")
    assert cookie
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert (await client.get("/api/auth/me")).json()["username"] == "alice"
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_login_duplicate_and_bad_credentials(client):
    assert (await client.post("/api/auth/register", json={"username": "bob", "password": "Bob-pass-1"})).status_code == 201
    duplicate = await client.post("/api/auth/register", json={"username": "bob", "password": "Bob-pass-1"})
    assert duplicate.status_code == 409
    bad = await client.post("/api/auth/login", json={"username": "bob", "password": "wrong-pass"})
    assert bad.status_code == 401
    assert (await client.post("/api/auth/login", json={"username": "bob", "password": "Bob-pass-1"})).status_code == 200


@pytest.mark.asyncio
async def test_admin_bootstrap_login(client):
    response = await client.post("/api/auth/login", json={"username": "test-admin", "password": "Admin-pass-1"})
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_anonymous_business_endpoint_requires_auth(client):
    response = await client.get("/api/conversations")
    assert response.status_code == 401
