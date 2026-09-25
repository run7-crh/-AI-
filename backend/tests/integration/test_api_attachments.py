"""Multipart attachment API coverage.

The suite is skipped in environments without python-multipart because
Starlette cannot parse multipart/form-data without that optional runtime
dependency.  Storage/context unit coverage remains runnable independently.
"""

pytest = __import__("pytest")
pytest.importorskip("multipart")

import io

from httpx import ASGITransport, AsyncClient
from asgi_lifespan import LifespanManager

from app.main import app
from tests.integration.conftest import login_admin


async def _client():
    manager = LifespanManager(app)
    await manager.__aenter__()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    await login_admin(client)
    return manager, client


async def _conversation(client):
    response = await client.post("/api/conversations", json={})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_multipart_upload_list_get_delete_and_cross_conversation_boundary():
    manager, client = await _client()
    try:
        conversation_id = await _conversation(client)
        other_id = await _conversation(client)
        response = await client.post(
            f"/api/conversations/{conversation_id}/attachments",
            files=[("files", ("notes.txt", io.BytesIO(b"hello"), "text/plain"))],
        )
        assert response.status_code == 201
        item = response.json()["attachments"][0]
        assert item["attachment_id"].startswith("att_")
        assert item["extraction_status"] == "ready"
        assert "storage_key" not in item

        listed = await client.get(f"/api/conversations/{conversation_id}/attachments")
        assert listed.status_code == 200 and len(listed.json()) == 1
        detail = await client.get(f"/api/conversations/{conversation_id}/attachments/{item['id']}")
        assert detail.status_code == 200
        cross = await client.get(f"/api/conversations/{other_id}/attachments/{item['id']}")
        assert cross.status_code == 404
        deleted = await client.delete(f"/api/conversations/{conversation_id}/attachments/{item['id']}")
        assert deleted.status_code == 200
    finally:
        await client.aclose()
        await manager.__aexit__(None, None, None)


