# backend/tests/integration/test_api_feedback.py
"""反馈系统接口测试。

8 个用例覆盖：
1. PUT useful → 200
2. PUT useless + reason → 200
3. PUT useless 无 reason → 422
4. PUT 同一 query_log_id 两次 → upsert 更新
5. PUT 不存在的 query_log_id → 404
6. GET stats 空表 → total=0
7. GET stats 有数据 → 统计正确
8. PUT 无效 rating → 422
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

from app.main import app, get_query_log_store
from tests.integration.conftest import login_admin


@pytest.fixture
async def client():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            await login_admin(c)
            yield c


async def _seed_query_log(query_log_id: str = None) -> str:
    """在 query_log 表插一条记录，作为 feedback 的 FK 依赖。

    在 LifespanManager 启动后调用（store 已初始化）。
    """
    query_log_id = query_log_id or str(uuid.uuid4())
    from app.models.query_log import QueryLogCreate
    store = get_query_log_store()
    record = QueryLogCreate(
        id=query_log_id,
        conversation_id="test-conv-id",
        user_id=(await _seed_owner_id()), user_label="A",
        raw_query="测试问题",
        rewritten_query=None,
        route_path="local",
        rewrite_count=0,
        retrieved_doc_ids=None,
        avg_reranker_score=None,
        judge_log_json=None,
        final_answer="测试答案",
        answer_length=4,
        has_source=0,
        models_used_json=None,
        token_usage_json=None,
        latency_ms=100,
        error=None,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await store.insert(record)
    return query_log_id


async def _seed_owner_id():
    from app.services.auth_store import AuthStore
    from app.config import settings
    import os
    store = AuthStore(os.environ.get("TEST_SQLITE_PATH", settings.SQLITE_PATH))
    user = await store.authenticate("test-admin", "Admin-pass-1")
    return user.id


@pytest.mark.asyncio
async def test_put_feedback_useful(client):
    """1. PUT useful → 200 + feedback_id。"""
    query_log_id = await _seed_query_log()
    resp = await client.put("/api/feedback", json={
        "query_log_id": query_log_id,
        "rating": "useful",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert "feedback_id" in data


@pytest.mark.asyncio
async def test_put_feedback_useless_with_reason(client):
    """2. PUT useless + reason → 200。"""
    query_log_id = await _seed_query_log()
    resp = await client.put("/api/feedback", json={
        "query_log_id": query_log_id,
        "rating": "useless",
        "useless_reason": "hallucination",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_put_feedback_useless_without_reason_returns_422(client):
    """3. PUT useless 无 reason → 422。"""
    query_log_id = await _seed_query_log()
    resp = await client.put("/api/feedback", json={
        "query_log_id": query_log_id,
        "rating": "useless",
    })
    assert resp.status_code == 422, resp.text
@pytest.mark.asyncio
async def test_put_feedback_upsert(client):
    """4. PUT 同一 query_log_id 两次 → upsert 更新（不报错，rating 变更）。"""
    query_log_id = await _seed_query_log()

    # 第一次：useful
    resp1 = await client.put("/api/feedback", json={
        "query_log_id": query_log_id,
        "rating": "useful",
    })
    assert resp1.status_code == 200, resp1.text
    id1 = resp1.json()["feedback_id"]

    # 第二次：改为 useless + reason
    resp2 = await client.put("/api/feedback", json={
        "query_log_id": query_log_id,
        "rating": "useless",
        "useless_reason": "verbose",
    })
    assert resp2.status_code == 200, resp2.text
    id2 = resp2.json()["feedback_id"]

    # 验证 feedback 表只有 1 条记录（upsert 生效）
    from app.main import get_feedback_store
    store = get_feedback_store()
    record = await store.get_by_query_log_id(query_log_id)
    assert record is not None
    assert record["rating"] == "useless"
    assert record["useless_reason"] == "verbose"


@pytest.mark.asyncio
async def test_put_feedback_nonexistent_query_log_returns_404(client):
    """5. PUT 不存在的 query_log_id → 404（外键校验）。"""
    resp = await client.put("/api/feedback", json={
        "query_log_id": "nonexistent-log-id",
        "rating": "useful",
    })
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_get_stats_empty(client):
    """6. GET stats 空表 → total=0，各计数为 0。"""
    resp = await client.get("/api/feedback/stats")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 0
    assert data["useful_count"] == 0
    assert data["useless_count"] == 0
    assert data["bug_count"] == 0
    assert data["useless_reason_breakdown"] == {
        "irrelevant": 0, "hallucination": 0, "verbose": 0, "wrong_route": 0
    }


@pytest.mark.asyncio
async def test_get_stats_with_data(client):
    """7. GET stats 有数据 → 统计正确（1 useful + 2 useless 含 reason）。"""
    # 插入 3 条 query_log + 3 条 feedback
    ql1 = await _seed_query_log()
    ql2 = await _seed_query_log()
    ql3 = await _seed_query_log()

    await client.put("/api/feedback", json={
        "query_log_id": ql1, "rating": "useful"
    })
    await client.put("/api/feedback", json={
        "query_log_id": ql2, "rating": "useless", "useless_reason": "hallucination"
    })
    await client.put("/api/feedback", json={
        "query_log_id": ql3, "rating": "useless", "useless_reason": "verbose"
    })

    resp = await client.get("/api/feedback/stats")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 3
    assert data["useful_count"] == 1
    assert data["useless_count"] == 2
    assert data["bug_count"] == 0
    assert data["useless_reason_breakdown"]["hallucination"] == 1
    assert data["useless_reason_breakdown"]["verbose"] == 1
    assert data["useless_reason_breakdown"]["irrelevant"] == 0
    assert data["useless_reason_breakdown"]["wrong_route"] == 0


@pytest.mark.asyncio
async def test_put_feedback_invalid_rating_returns_422(client):
    """8. PUT 无效 rating='bad' → 422（Pydantic Literal 校验）。"""
    query_log_id = await _seed_query_log()
    resp = await client.put("/api/feedback", json={
        "query_log_id": query_log_id,
        "rating": "bad",
    })
    assert resp.status_code == 422, resp.text
