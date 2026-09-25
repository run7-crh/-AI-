# backend/tests/integration/test_api_index.py
import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from unittest.mock import patch, MagicMock, AsyncMock
from app.main import app
from tests.integration.conftest import login_admin
from app.api import index as index_api


@pytest.mark.asyncio
async def test_rebuild_index():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await login_admin(c)
            with patch("app.api.index.get_indexer") as mock_get, \
                 patch("app.api.index.build_knowledge_graph", new_callable=AsyncMock) as mock_graph:
                mock_idx = MagicMock()
                mock_idx.build = MagicMock()
                mock_idx.chroma_collection = MagicMock()
                mock_idx.chroma_collection.count = MagicMock(return_value=18)
                mock_idx.chroma_collection.get = MagicMock(return_value={
                    "metadatas": [
                        {"document_id": "doc-a"},
                        {"document_id": "doc-a"},
                        {"document_id": "doc-b"},
                    ]
                })
                mock_get.return_value = mock_idx

                resp = await c.post("/api/index/rebuild")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["doc_count"] == 2
    assert data["vector_count"] == 18
    assert data["graph_built"] is True
    mock_graph.assert_awaited_once()


@pytest.mark.asyncio
async def test_rebuild_index_graph_failure_not_blocking():
    """图谱构建失败不阻塞索引重建：graph_built=False 但整体仍 success。"""
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await login_admin(c)
            with patch("app.api.index.get_indexer") as mock_get, \
                 patch("app.api.index.build_knowledge_graph", new_callable=AsyncMock) as mock_graph:
                mock_idx = MagicMock()
                mock_idx.build = MagicMock()
                mock_idx.chroma_collection = MagicMock()
                mock_idx.chroma_collection.count = MagicMock(return_value=18)
                mock_idx.chroma_collection.get = MagicMock(return_value={"metadatas": []})
                mock_get.return_value = mock_idx
                mock_graph.side_effect = RuntimeError("LLM 全挂")

                resp = await c.post("/api/index/rebuild")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["graph_built"] is False


@pytest.mark.asyncio
async def test_rebuild_index_returns_conflict_when_already_running():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await login_admin(c)
            await index_api._rebuild_lock.acquire()
            try:
                resp = await c.post("/api/index/rebuild")
            finally:
                index_api._rebuild_lock.release()
    assert resp.status_code == 409
