# backend/tests/integration/test_api_graph.py
"""GET /api/graph 集成测试：404 / 200+ETag / 304 / 损坏 JSON。"""
import json

import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from app.main import app
from app.config import settings

KG_SAMPLE = {
    "built_at": "2026-08-16T12:00:00",
    "nodes": [
        {"id": "agent", "title": "Agent", "summary": "s", "category": "Agent工程",
         "tags": ["AI"], "file": "a.md", "degree": 1, "aliases": []},
        {"id": "rag", "title": "RAG", "summary": "s", "category": "检索增强",
         "tags": ["AI"], "file": "r.md", "degree": 1, "aliases": []},
    ],
    "edges": [
        {"source": "agent", "target": "rag", "type": "依赖", "via": "rule", "description": ""},
    ],
}


async def _get(client, headers=None):
    return await client.get("/api/graph", headers=headers or {})


@pytest.mark.asyncio
async def test_graph_404_when_not_built(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KG_JSON_PATH", str(tmp_path / "absent.json"))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await _get(c)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "knowledge graph not built"


@pytest.mark.asyncio
async def test_graph_200_with_etag(tmp_path, monkeypatch):
    kg = tmp_path / "kg.json"
    kg.write_text(json.dumps(KG_SAMPLE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "KG_JSON_PATH", str(kg))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await _get(c)
    assert resp.status_code == 200
    assert resp.json() == KG_SAMPLE
    etag = resp.headers["etag"]
    assert etag  # built_at 哈希

    # 同 ETag 再请求 → 304
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp304 = await _get(c, headers={"If-None-Match": etag})
    assert resp304.status_code == 304


@pytest.mark.asyncio
async def test_graph_500_when_corrupted(tmp_path, monkeypatch):
    kg = tmp_path / "kg.json"
    kg.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(settings, "KG_JSON_PATH", str(kg))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await _get(c)
    assert resp.status_code == 500
