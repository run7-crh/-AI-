# backend/tests/integration/test_api_conversations.py
import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from app.main import app


@pytest.fixture
async def client():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_create_conversation_default_title(client):
    resp = await client.post("/api/conversations", json={})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "新会话"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_conversations(client):
    await client.post("/api/conversations", json={"title": "会话1"})
    await client.post("/api/conversations", json={"title": "会话2"})
    resp = await client.get("/api/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2


@pytest.mark.asyncio
async def test_get_conversation_detail(client):
    create = await client.post("/api/conversations", json={"title": "测试"})
    conv_id = create.json()["id"]
    resp = await client.get(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "测试"


@pytest.mark.asyncio
async def test_get_nonexistent_conversation_returns_404(client):
    resp = await client.get("/api/conversations/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation(client):
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    resp = await client.delete(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    resp2 = await client.get(f"/api/conversations/{conv_id}")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_update_conversation_title(client):
    create = await client.post("/api/conversations", json={"title": "旧"})
    conv_id = create.json()["id"]
    resp = await client.patch(f"/api/conversations/{conv_id}", json={"title": "新"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "新"
