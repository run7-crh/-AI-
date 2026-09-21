import pytest
from httpx import ASGITransport, AsyncClient
from asgi_lifespan import LifespanManager

from app.main import app, get_query_log_store
from app.models.query_log import QueryLogCreate
from datetime import datetime, timezone
import uuid


async def register(client, username, password):
    response = await client.post("/api/auth/register", json={"username": username, "password": password})
    assert response.status_code == 201, response.text


@pytest.fixture
async def clients():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as alice:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as bob:
                await register(alice, "alice-authz", "Alice-pass-1")
                await register(bob, "bob-authz", "Bob-pass-1")
                yield alice, bob


@pytest.mark.asyncio
async def test_foreign_conversation_is_hidden_from_all_mutations_and_chat(clients):
    alice, bob = clients
    created = await alice.post("/api/conversations", json={"title": "private"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    assert (await bob.get(f"/api/conversations/{conversation_id}")).status_code == 404
    assert (await bob.patch(f"/api/conversations/{conversation_id}", json={"title": "stolen"})).status_code == 404
    assert (await bob.delete(f"/api/conversations/{conversation_id}")).status_code == 404
    assert (await bob.post("/api/chat", json={"conversation_id": conversation_id, "message": "hello"})).status_code == 404
    assert (await bob.get(f"/api/conversations/{conversation_id}/attachments")).status_code == 404
    assert (await bob.post(f"/api/conversations/{conversation_id}/attachments", files={"files": ("x.txt", b"x", "text/plain")})).status_code == 404


@pytest.mark.asyncio
async def test_foreign_delete_does_not_remove_owner_attachment(clients):
    alice, bob = clients
    conversation_id = (await alice.post("/api/conversations", json={})).json()["id"]
    upload = await alice.post(
        f"/api/conversations/{conversation_id}/attachments",
        files={"files": ("keep.txt", b"keep", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    attachment_id = upload.json()["attachments"][0]["id"]
    assert (await bob.delete(f"/api/conversations/{conversation_id}")).status_code == 404
    assert (await alice.get(f"/api/conversations/{conversation_id}/attachments/{attachment_id}")).status_code == 200


@pytest.mark.asyncio
async def test_feedback_rejects_foreign_query_log_and_stats_requires_admin(clients):
    alice, bob = clients
    conversation_id = (await alice.post("/api/conversations", json={})).json()["id"]
    log_id = str(uuid.uuid4())
    await get_query_log_store().insert(QueryLogCreate(
        id=log_id, conversation_id=conversation_id, user_id=(await alice.get("/api/auth/me")).json()["id"],
        raw_query="q", created_at=datetime.now(timezone.utc).isoformat(),
    ))
    response = await bob.put("/api/feedback", json={"query_log_id": log_id, "rating": "useful"})
    assert response.status_code == 404
    assert (await bob.get("/api/feedback/stats")).status_code == 403


@pytest.mark.asyncio
async def test_anonymous_business_endpoints_require_auth_and_health_is_public():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/conversations")).status_code == 401
            assert (await client.get("/api/graph")).status_code == 401
            assert (await client.get("/api/health")).status_code == 200
