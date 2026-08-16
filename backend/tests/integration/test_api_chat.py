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


# ---------- 思考过程可视化：stage 结构升级 + node_end + reasoning 事件 ----------

def _make_mock_graph(events: list[dict]):
    async def mock_stream(*args, **kwargs):
        for e in events:
            yield e

    return type("G", (), {"astream_events": mock_stream})()


async def _collect_sse_events(client, conv_id: str, mock_graph, monkeypatch) -> list[dict]:
    from app.api import chat as chat_module

    monkeypatch.setattr(chat_module, "get_graph", lambda: mock_graph)
    events = []
    async with client.stream(
        "POST", "/api/chat", json={"conversation_id": conv_id, "message": "你好"},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


@pytest.mark.asyncio
async def test_chat_stage_event_has_node_and_label(client, monkeypatch):
    """stage 事件 data 从裸 string 升级为 {node, label}；LangGraph 总节点不发 stage。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph([
        {"event": "on_chain_start", "name": "LangGraph", "data": {}},
        {"event": "on_chain_start", "name": "rewrite_query", "data": {}},
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "t", "route_path": "chitchat", "judge_log": []}},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    stages = [e for e in events if e["type"] == "stage"]
    assert len(stages) == 1  # LangGraph 本身不发 stage
    assert stages[0]["data"] == {"node": "rewrite_query", "label": "正在理解问题..."}


@pytest.mark.asyncio
async def test_chat_emits_node_end_with_whitelisted_output(client, monkeypatch):
    """node_end 事件：含 node/label/duration_ms/output，output 走白名单过滤。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph([
        {"event": "on_chain_start", "name": "rewrite_query", "data": {}},
        {
            "event": "on_chain_end",
            "name": "rewrite_query",
            "data": {"output": {"rewritten_query": "什么是 RAG", "route_path": "local"}},
        },
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "t", "route_path": "chitchat", "judge_log": []}},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    node_ends = [e for e in events if e["type"] == "node_end"]
    assert len(node_ends) == 1  # LangGraph 的 on_chain_end 不产生 node_end
    payload = node_ends[0]["data"]
    assert payload["node"] == "rewrite_query"
    assert payload["label"] == "正在理解问题..."
    assert isinstance(payload["duration_ms"], int)
    assert payload["duration_ms"] >= 0
    # route_path 不在白名单内，被过滤
    assert payload["output"] == {"rewritten_query": "什么是 RAG"}


@pytest.mark.asyncio
async def test_chat_emits_reasoning_from_chunk(client, monkeypatch):
    """chunk 含 reasoning_content 时下发 reasoning 事件（增量文本）。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph([
        {"event": "on_llm_stream", "data": {"chunk": {
            "content": "",
            "additional_kwargs": {"reasoning_content": "用户在问 RAG..."},
        }}},
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "t", "route_path": "chitchat", "judge_log": []}},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    reasonings = [e for e in events if e["type"] == "reasoning"]
    assert len(reasonings) == 1
    assert reasonings[0]["data"] == "用户在问 RAG..."


@pytest.mark.asyncio
async def test_chat_no_reasoning_when_chunk_lacks_field(client, monkeypatch):
    """普通模型 chunk 无 reasoning_content → 不发 reasoning 事件。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph([
        {"event": "on_llm_stream", "data": {"chunk": {"content": "答"}}},
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "t", "route_path": "chitchat", "judge_log": []}},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    assert "reasoning" not in [e["type"] for e in events]
    assert "token" in [e["type"] for e in events]
