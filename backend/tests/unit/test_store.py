import pytest
import tempfile
import os
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
