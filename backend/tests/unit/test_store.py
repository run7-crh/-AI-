import pytest
import tempfile
import os
import aiosqlite
import sqlite3
from app.services.conversation_store import ConversationStore

@pytest.fixture
async def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = ConversationStore(db_path)
    await s.init()
    yield s
    os.unlink(db_path)

@pytest.mark.asyncio
async def test_create_and_get_conversation(store):
    conv_id = await store.create_conversation(title="测试")
    conv = await store.get_conversation(conv_id)
    assert conv is not None
    assert conv["title"] == "测试"
    assert conv["message_count"] == 0

@pytest.mark.asyncio
async def test_list_conversations_ordered_by_updated(store):
    id1 = await store.create_conversation(title="会话1")
    id2 = await store.create_conversation(title="会话2")
    # Windows clock precision can give both inserts the same timestamp.
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute("UPDATE conversations SET updated_at = ?", ("2026-09-09T00:00:00+00:00",))
        await db.commit()
    convs = await store.list_conversations()
    assert convs[0]["id"] == id2
    assert convs[1]["id"] == id1

@pytest.mark.asyncio
async def test_add_message_updates_count_and_history(store):
    conv_id = await store.create_conversation()
    await store.add_message(conv_id, role="user", content="问题1")
    await store.add_message(conv_id, role="assistant", content="回答1",
                            route_path="local", sources=[{"x": 1}], judge_log=[{"y": 2}])
    history = await store.get_history(conv_id, limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    conv = await store.get_conversation(conv_id)
    assert conv["message_count"] == 2
    assert conv["messages"][1]["sources"] == [{"x": 1}]
    assert conv["messages"][1]["judge_log"] == [{"y": 2}]


@pytest.mark.asyncio
async def test_add_message_persists_feedback_binding_and_quality_warning(store):
    conv_id = await store.create_conversation()
    await store.add_message(
        conv_id,
        role="assistant",
        content="答案",
        quality_warning="请谨慎核验",
        query_log_id="log-1",
    )

    conv = await store.get_conversation(conv_id)
    message = conv["messages"][0]
    assert message["quality_warning"] == "请谨慎核验"
    assert message["query_log_id"] == "log-1"


@pytest.mark.asyncio
async def test_add_message_persists_safety_and_intent_metadata(store):
    conv_id = await store.create_conversation()
    await store.add_message(
        conv_id,
        role="assistant",
        content="请先降落并断电。",
        safety_flag=True,
        safety_level="high",
        safety_situation="in_flight",
        escalation_required=True,
        intent="flight_safety",
        metadata_constraints={"product_model": "mini_4_pro", "component": "battery"},
        document_type_priority=["safety", "troubleshooting", "sop"],
    )

    message = (await store.get_conversation(conv_id))["messages"][0]
    assert message["safety_flag"] is True
    assert message["safety_level"] == "high"
    assert message["safety_situation"] == "in_flight"
    assert message["escalation_required"] is True
    assert message["intent"] == "flight_safety"
    assert message["metadata_constraints"] == {"product_model": "mini_4_pro", "component": "battery"}
    assert message["document_type_priority"] == ["safety", "troubleshooting", "sop"]


@pytest.mark.asyncio
async def test_init_migrates_legacy_messages_table(tmp_path):
    """Existing DBs created before trace metadata remain readable after init."""
    db_path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(db_path) as db:
        await db.executescript("""
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                message_count INTEGER DEFAULT 0
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL,
                route_path TEXT, sources TEXT, judge_log TEXT,
                created_at TEXT NOT NULL
            );
        """)
        await db.commit()

    store = ConversationStore(db_path)
    await store.init()
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in await cursor.fetchall()}
    assert {"safety_flag", "safety_level", "safety_situation", "escalation_required", "intent", "metadata_constraints", "document_type_priority"} <= columns
    conv_id = await store.create_conversation()
    await store.add_message(conv_id, role="assistant", content="旧库")
    message = (await store.get_conversation(conv_id))["messages"][0]
    assert message["quality_warning"] is None
    assert message["query_log_id"] is None
    assert message["safety_flag"] is None
    assert message["intent"] is None
    assert message["metadata_constraints"] is None
    assert message["document_type_priority"] is None

@pytest.mark.asyncio
async def test_delete_conversation_cascades_messages(store):
    conv_id = await store.create_conversation()
    await store.add_message(conv_id, role="user", content="x")
    ok = await store.delete_conversation(conv_id)
    assert ok is True
    conv = await store.get_conversation(conv_id)
    assert conv is None

@pytest.mark.asyncio
async def test_update_conversation_title(store):
    conv_id = await store.create_conversation(title="旧标题")
    ok = await store.update_conversation_title(conv_id, "新标题")
    assert ok is True
    conv = await store.get_conversation(conv_id)
    assert conv["title"] == "新标题"

@pytest.mark.asyncio
async def test_get_history_respects_limit(store):
    conv_id = await store.create_conversation()
    for i in range(5):
        await store.add_message(conv_id, role="user", content=f"问题{i}")
    history = await store.get_history(conv_id, limit=3)
    assert len(history) == 3
    assert history[-1]["content"] == "问题4"


@pytest.mark.asyncio
async def test_sqlite_connections_enable_foreign_keys_and_wal(store):
    with pytest.raises(sqlite3.IntegrityError):
        await store.add_message("missing", role="user", content="x")
    async with aiosqlite.connect(store.db_path) as db:
        cursor = await db.execute("PRAGMA journal_mode")
        assert (await cursor.fetchone())[0].lower() == "wal"


@pytest.mark.asyncio
async def test_delete_conversation_removes_query_logs(store):
    conv_id = await store.create_conversation()
    async with aiosqlite.connect(store.db_path) as db:
        await db.execute(
            "CREATE TABLE query_log (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL)"
        )
        await db.execute(
            "INSERT INTO query_log (id, conversation_id) VALUES (?, ?)",
            ("log-1", conv_id),
        )
        await db.commit()

    assert await store.delete_conversation(conv_id) is True
    async with aiosqlite.connect(store.db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM query_log")
        assert (await cursor.fetchone())[0] == 0
