# backend/tests/unit/test_fault_progress.py
"""阶段 2：排查失败计数——可持久化、确认信号、fault_key 派生与落库。"""
import asyncio
import json
import tempfile
import os
import pytest
from datetime import datetime, timezone

from app.services.fault_progress_service import (
    FaultProgressStore,
    is_confirmed_ineffective,
    FAILED_ATTEMPT_THRESHOLD,
)
from app.services.query_log_service import QueryLogStore
from app.models.query_log import QueryLogCreate
import app.main  # noqa: F401  # 先完成 main 装载（chat 依赖 main 的 store getter，顺序颠倒会循环导入）
from app.api.chat import _derive_fault_key


@pytest.fixture
def stores():
    db_path = tempfile.mktemp(suffix=".db")
    os.environ["TEST_SQLITE_PATH"] = db_path  # 供后续集成测试隔离
    ql = QueryLogStore(db_path)
    fp = FaultProgressStore(db_path)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(ql.init())
    loop.run_until_complete(fp.init())
    yield ql, fp, db_path
    if os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except PermissionError:
            pass


# ============================================================================
# 信号判定：确认执行 + 仍无效
# ============================================================================
def test_confirmed_ineffective_positive():
    assert is_confirmed_ineffective("我按步骤校准了，还是不行")
    assert is_confirmed_ineffective("照做了，依然报错")


def test_confirmed_ineffective_negative():
    assert not is_confirmed_ineffective("还是不行")          # 只有无效无确认
    assert not is_confirmed_ineffective("我按步骤做了")      # 只有确认无无效
    assert not is_confirmed_ineffective("新买的无人机怎么对频")  # 普通追问
    assert not is_confirmed_ineffective("")


# ============================================================================
# 计数存储：累加 / 阈值 / 隔离
# ============================================================================
@pytest.mark.asyncio
async def test_increment_and_threshold(stores):
    _, fp, _ = stores
    assert await fp.has_repeated_failure("c1") is False     # 0 次
    await fp.increment("c1", "mini_4_pro__compass_abnormal")
    assert await fp.has_repeated_failure("c1") is False     # 1 次未达阈值
    await fp.increment("c1", "mini_4_pro__compass_abnormal")
    assert await fp.has_repeated_failure("c1") is True      # 2 次达到阈值
    assert await fp.has_repeated_failure("c2") is False     # 会话隔离
    progress = await fp.list_progress("c1")
    assert progress[0]["fault_key"] == "mini_4_pro__compass_abnormal"
    assert progress[0]["failed_attempts"] == FAILED_ATTEMPT_THRESHOLD


@pytest.mark.asyncio
async def test_record_confirmation_counts_only_valid_signal(stores):
    ql, fp, _ = stores
    # 先写一条带 fault_key 的"上一轮回答"
    await ql.insert(QueryLogCreate(
        id="q1", conversation_id="c1", raw_query="罗盘异常", fault_key="mini_4_pro__compass_abnormal",
        created_at=datetime.now(timezone.utc).isoformat(),
    ))
    assert await fp.record_confirmation(ql, "c1", "普通追问，不计数") is False
    assert await fp.record_confirmation(ql, "c1", "按步骤校准了还是不行") is True
    assert (await fp.list_progress("c1"))[0]["failed_attempts"] == 1
    # query_log_store 为 None 时跳过不抛错
    assert await fp.record_confirmation(None, "c1", "按步骤做了没用") is False


@pytest.mark.asyncio
async def test_record_confirmation_without_prior_fault_key(stores):
    ql, fp, _ = stores
    # 无任何带 fault_key 的历史记录 → 不计数
    assert await fp.record_confirmation(ql, "c9", "按步骤做了没用") is False


# ============================================================================
# query_log：fault_key 落库与查询
# ============================================================================
@pytest.mark.asyncio
async def test_query_log_fault_key_roundtrip(stores):
    ql, _, _ = stores
    await ql.insert(QueryLogCreate(
        id="q2", conversation_id="c1", raw_query="q", fault_key="m350__rtk_signal_abnormal",
        created_at=datetime.now(timezone.utc).isoformat(),
    ))
    await ql.insert(QueryLogCreate(
        id="q3", conversation_id="c1", raw_query="q", fault_key=None,
        created_at=datetime.now(timezone.utc).isoformat(),
    ))
    latest = await ql.get_latest_fault_key("c1")
    # 最近一条带 fault_key 的是 q2（q3 为 NULL 被跳过）
    assert latest["id"] == "q2"
    assert latest["fault_key"] == "m350__rtk_signal_abnormal"


@pytest.mark.asyncio
async def test_query_log_persists_safety_and_intent_metadata(stores):
    ql, _, _ = stores
    await ql.insert(QueryLogCreate(
        id="q-metadata", conversation_id="c1", raw_query="罗盘怎么校准",
        safety_flag=False, safety_level="none", safety_situation="unknown",
        escalation_required=False, intent="sop",
        metadata_constraints={"product_model": "mini_4_pro", "component": "compass"},
        document_type_priority=["sop", "troubleshooting"],
        created_at=datetime.now(timezone.utc).isoformat(),
    ))
    row = (await ql.get_by_conversation("c1"))[-1]
    assert row["safety_flag"] == 0
    assert row["safety_level"] == "none"
    assert row["escalation_required"] == 0
    assert row["intent"] == "sop"
    assert json.loads(row["metadata_constraints"]) == {"product_model": "mini_4_pro", "component": "compass"}
    assert json.loads(row["document_type_priority"]) == ["sop", "troubleshooting"]


@pytest.mark.asyncio
async def test_query_log_migration_adds_phase41_columns(tmp_path):
    import aiosqlite
    db_path = str(tmp_path / "legacy-query-log.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute("CREATE TABLE query_log (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, raw_query TEXT NOT NULL, created_at TEXT NOT NULL)")
        await db.execute("INSERT INTO query_log VALUES ('old', 'c1', '旧记录', '2026-01-01')")
        await db.commit()
    ql = QueryLogStore(db_path)
    await ql.init()
    row = (await ql.list_recent())[0]
    assert row["safety_flag"] is None
    assert row["intent"] is None
    assert row["metadata_constraints"] is None


@pytest.mark.asyncio
async def test_query_log_migration_adds_fault_key_column():
    """旧库（无 fault_key 列）init 时自动补列，旧数据可读。"""
    import aiosqlite
    db_path = tempfile.mktemp(suffix=".db")
    # 手工建旧 schema
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE query_log (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,"
            " raw_query TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        await db.execute(
            "INSERT INTO query_log VALUES ('old1', 'c1', '旧记录', '2026-01-01')"
        )
        await db.commit()
    ql = QueryLogStore(db_path)
    await ql.init()  # 迁移：补 fault_key 列
    rows = await ql.list_recent(limit=5)
    assert rows[0]["id"] == "old1"
    assert rows[0]["fault_key"] is None            # 旧行为 NULL
    await ql.insert(QueryLogCreate(               # 新写入带 fault_key
        id="new1", conversation_id="c1", raw_query="q", fault_key="k",
        created_at=datetime.now(timezone.utc).isoformat(),
    ))
    assert (await ql.get_latest_fault_key("c1"))["fault_key"] == "k"
    if os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except PermissionError:
            pass


# ============================================================================
# fault_key 派生：来自故障类证据元数据
# ============================================================================
def test_derive_fault_key_prefers_troubleshooting():
    state = {"route_path": "local", "retrieval_result": [
        {"content": "产品参数", "source": "p.md", "document_type": "product"},
        {"content": "罗盘故障", "source": "t.md", "document_type": "troubleshooting",
         "product_model": "mini_4_pro", "fault_type": "compass_abnormal"},
    ]}
    assert _derive_fault_key(state) == "mini_4_pro__compass_abnormal"


def test_derive_fault_key_accepts_case_docs():
    state = {"route_path": "local", "retrieval_result": [
        {"content": "案例", "source": "c.md", "document_type": "case",
         "product_model": "matrice_350_rtk", "component": "rtk"},
    ]}
    assert _derive_fault_key(state) == "matrice_350_rtk__rtk"


def test_derive_fault_key_none_without_fault_evidence():
    assert _derive_fault_key({"route_path": "local", "retrieval_result": [
        {"content": "产品参数", "source": "p.md", "document_type": "product"},
    ]}) is None
    assert _derive_fault_key({"route_path": "online"}) is None
    assert _derive_fault_key({}) is None
