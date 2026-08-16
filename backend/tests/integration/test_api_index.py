# backend/tests/integration/test_api_index.py
import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from unittest.mock import patch, MagicMock, AsyncMock
from app.main import app


@pytest.mark.asyncio
async def test_rebuild_index():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            with patch("app.api.index.get_indexer") as mock_get, \
                 patch("app.api.index.build_knowledge_graph", new_callable=AsyncMock) as mock_graph:
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
    assert data["graph_built"] is True
    mock_graph.assert_awaited_once()


@pytest.mark.asyncio
async def test_rebuild_index_graph_failure_not_blocking():
    """图谱构建失败不阻塞索引重建：graph_built=False 但整体仍 success。"""
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            with patch("app.api.index.get_indexer") as mock_get, \
                 patch("app.api.index.build_knowledge_graph", new_callable=AsyncMock) as mock_graph:
                mock_idx = MagicMock()
                mock_idx.build = MagicMock()
                mock_idx.chroma_collection = MagicMock()
                mock_idx.chroma_collection.count = MagicMock(return_value=18)
                mock_get.return_value = mock_idx
                mock_graph.side_effect = RuntimeError("LLM 全挂")

                resp = await c.post("/api/index/rebuild")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["graph_built"] is False
