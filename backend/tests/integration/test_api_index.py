# backend/tests/integration/test_api_index.py
import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from unittest.mock import patch, MagicMock
from app.main import app


@pytest.mark.asyncio
async def test_rebuild_index():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            with patch("app.api.index.get_indexer") as mock_get:
                mock_idx = MagicMock()
                mock_idx.build = MagicMock()
                mock_idx.chroma_collection = MagicMock()
                mock_idx.chroma_collection.count = MagicMock(return_value=18)
                mock_get.return_value = mock_idx

                resp = await c.post("/api/index/rebuild")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["doc_count"] == 18
