# backend/tests/integration/test_api_chat.py
import pytest
import json
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from app.main import app
from tests.integration.conftest import login_admin


async def _always_fail_insert(record):
    raise OSError("log write failure")


@pytest.fixture
async def client():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await login_admin(c)
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
async def test_chat_emits_final_event_for_non_streaming_fallback(client, monkeypatch):
    """节点降级答案没有 token 事件时，前端仍能收到完整答案。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    graph = _make_mock_graph([
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "final_answer": "降级答案",
                    "route_path": "local",
                    "judge_log": [],
                }
            },
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)
    assert {e["type"] for e in events} >= {"final", "meta", "done"}
    assert next(e for e in events if e["type"] == "final")["data"] == "降级答案"


@pytest.mark.asyncio
async def test_chat_persists_response_metadata_before_feedback_id_is_emitted(client, monkeypatch):
    """The query log and message metadata exist when meta reaches the client."""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    graph = _make_mock_graph([
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {
                "output": {
                    "final_answer": "答案",
                    "route_path": "local",
                    "judge_log": [],
                    "quality_warning": "请核验",
                }
            },
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)
    meta = next(e["data"] for e in events if e["type"] == "meta")
    assert meta["final_answer"] == "答案"
    assert meta["query_log_id"]

    history = (await client.get(f"/api/conversations/{conv_id}")).json()
    assistant = history["messages"][-1]
    assert assistant["quality_warning"] == "请核验"
    assert assistant["query_log_id"] == meta["query_log_id"]

    # Feedback immediately after receiving meta must see the already-inserted
    # diagnostic row instead of racing the response finalizer.
    feedback = await client.put(
        "/api/feedback",
        json={"query_log_id": meta["query_log_id"], "rating": "useful"},
    )
    assert feedback.status_code == 200


@pytest.mark.asyncio
async def test_chat_persists_safety_and_intent_fields_for_history(client, monkeypatch):
    """历史会话透传已由后端生成的安全、升级和检索元数据。"""
    conv_id = (await client.post("/api/conversations", json={})).json()["id"]
    graph = _make_mock_graph([{
        "event": "on_chain_end", "name": "LangGraph",
        "data": {"output": {
            "final_answer": "请先降落。",
            "route_path": "local",
            "judge_log": [],
            "safety_flag": True,
            "safety_level": "high",
            "safety_situation": "in_flight",
            "escalation_required": True,
            "intent": "flight_safety",
            "metadata_constraints": {"product_model": "mini_4_pro"},
            "document_type_priority": ["safety", "troubleshooting"],
        }},
    }])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)
    meta = next(e["data"] for e in events if e["type"] == "meta")
    assert meta["intent"] == "flight_safety"
    history = (await client.get(f"/api/conversations/{conv_id}")).json()
    message = history["messages"][-1]
    assert message["safety_flag"] is True
    assert message["safety_level"] == "high"
    assert message["safety_situation"] == "in_flight"
    assert message["escalation_required"] is True
    assert message["intent"] == "flight_safety"
    assert message["metadata_constraints"] == {"product_model": "mini_4_pro"}
    assert message["document_type_priority"] == ["safety", "troubleshooting"]
    from app.main import get_query_log_store
    logs = await get_query_log_store().get_by_conversation(conv_id)
    assert logs[-1]["safety_flag"] == 1
    assert logs[-1]["escalation_required"] == 1
    assert logs[-1]["intent"] == "flight_safety"
    assert json.loads(logs[-1]["metadata_constraints"]) == {"product_model": "mini_4_pro"}


@pytest.mark.asyncio
async def test_chat_does_not_publish_query_log_id_when_log_write_fails(client, monkeypatch):
    """A failed diagnostic write must not expose an unusable feedback ID."""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    graph = _make_mock_graph([
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "答案", "route_path": "local", "judge_log": []}},
        },
    ])

    from app.main import get_query_log_store
    log_store = get_query_log_store()
    monkeypatch.setattr(log_store, "insert", _always_fail_insert)
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    meta = next(e["data"] for e in events if e["type"] == "meta")
    assert meta["query_log_id"] is None
    history = (await client.get(f"/api/conversations/{conv_id}")).json()
    assert history["messages"][-1]["query_log_id"] is None


@pytest.mark.asyncio
async def test_chat_does_not_publish_id_without_query_log_store(client, monkeypatch):
    conv_id = (await client.post("/api/conversations", json={})).json()["id"]
    from app.api import chat as chat_module
    monkeypatch.setattr(chat_module, "get_query_log_store", lambda: None)
    graph = _make_mock_graph([{
        "event": "on_chain_end", "name": "LangGraph",
        "data": {"output": {"final_answer": "答案", "route_path": "local"}},
    }])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)
    meta = next(e["data"] for e in events if e["type"] == "meta")
    assert meta["query_log_id"] is None
    history = (await client.get(f"/api/conversations/{conv_id}")).json()
    assert history["messages"][-1]["query_log_id"] is None


@pytest.mark.asyncio
async def test_chat_does_not_publish_id_when_only_finally_retry_succeeds(client, monkeypatch):
    """A finally-block retry may persist the log, but cannot retroactively alter meta."""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    graph = _make_mock_graph([
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "答案", "route_path": "local", "judge_log": []}},
        },
    ])

    from app.main import get_query_log_store
    log_store = get_query_log_store()
    original_insert = log_store.insert
    attempts = 0

    async def fail_once(record):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary log failure")
        return await original_insert(record)

    monkeypatch.setattr(log_store, "insert", fail_once)
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)
    meta = next(e["data"] for e in events if e["type"] == "meta")
    assert meta["query_log_id"] is None
    assert attempts == 2
    assert await log_store.count() == 1


@pytest.mark.asyncio
async def test_chat_filters_error_evidence_and_uses_web_for_online_route(client, monkeypatch):
    """Online metadata/logs contain only usable web evidence, never stale local/error entries."""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    web_evidence = {
        "source_type": "web", "source": "官方资料", "content": "最新内容",
        "title": "官方资料", "url": "https://example.com",
    }
    graph = _make_mock_graph([
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {
                "final_answer": "答案", "route_path": "online", "judge_log": [],
                "retrieval_result": [{"source": "stale-local.md", "content": "旧内容"}],
                "web_search_result": [
                    {"source": "联网搜索失败", "content": "联网搜索失败", "is_error": True},
                    {"source": "empty", "content": "  "}, None, "legacy-error", web_evidence,
                ],
            }},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)
    meta = next(e["data"] for e in events if e["type"] == "meta")
    assert meta["sources"] == [web_evidence]

    history = (await client.get(f"/api/conversations/{conv_id}")).json()
    assert history["messages"][-1]["sources"] == [web_evidence]

    from app.main import get_query_log_store
    logs = await get_query_log_store().get_by_conversation(conv_id)
    assert json.loads(logs[0]["retrieved_doc_ids"]) == ["官方资料"]


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
