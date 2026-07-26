# backend/tests/integration/test_api_chat.py
import pytest
import json
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
async def test_chat_returns_404_for_nonexistent_conversation(client):
    resp = await client.post(
        "/api/chat", json={"conversation_id": "nonexistent", "message": "x"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_chat_returns_sse_stream(client, monkeypatch):
    """验证 /api/chat 返回 SSE 流。"""
    # 创建会话
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    # mock graph.astream_events
    async def mock_stream(*args, **kwargs):
        yield {"event": "on_chain_start", "name": "rewrite_query", "data": {}}
        yield {"event": "on_llm_stream", "data": {"chunk": {"content": "测试"}}}
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "final_answer": "测试",
                    "route_path": "local",
                    "judge_log": [],
                }
            },
        }

    from app.api import chat as chat_module

    mock_graph = type("G", (), {"astream_events": mock_stream})()
    monkeypatch.setattr(chat_module, "get_graph", lambda: mock_graph)

    async with client.stream(
        "POST",
        "/api/chat",
        json={"conversation_id": conv_id, "message": "你好"},
    ) as resp:
        assert resp.status_code == 200
        events = []
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))

        types = [e["type"] for e in events]
        assert "stage" in types
        assert "token" in types
        assert "done" in types


@pytest.mark.asyncio
async def test_chat_rejects_empty_message(client):
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    resp = await client.post(
        "/api/chat", json={"conversation_id": conv_id, "message": ""}
    )
    assert resp.status_code == 422
