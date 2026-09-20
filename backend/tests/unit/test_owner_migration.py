import aiosqlite
import pytest

from app.services.auth_store import AuthStore
from app.services.query_log_service import QueryLogStore
from app.models.query_log import QueryLogCreate


@pytest.mark.asyncio
async def test_legacy_owner_migration_and_query_log_delete(tmp_path):
    path = str(tmp_path / "legacy.db")
    async with aiosqlite.connect(path) as db:
        await db.executescript("CREATE TABLE conversations(id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT); CREATE TABLE query_log(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, raw_query TEXT NOT NULL, created_at TEXT NOT NULL);")
        await db.execute("INSERT INTO conversations VALUES ('c1','t','x','x')")
        await db.execute("INSERT INTO query_log VALUES ('q1','c1','hello','x')")
        await db.commit()
    store = AuthStore(path)
    await store.init(admin_username="admin", admin_password="admin-pass")
    admin = (await store.list_users())[0]
    async with aiosqlite.connect(path) as db:
        assert (await (await db.execute("SELECT user_id FROM conversations")).fetchone())[0] == admin.id
        assert (await (await db.execute("SELECT user_id FROM query_log")).fetchone())[0] == admin.id
    ql = QueryLogStore(path)
    await ql.init()
    await ql.delete_by_user(admin.id)
    assert await ql.count() == 0

@pytest.mark.asyncio
async def test_owner_backfill_preserves_conversation_owner_and_cascade(tmp_path):
    path=str(tmp_path/"o.db"); s=AuthStore(path); await s.init(admin_username="admin",admin_password="admin-pass")
    u=await s.register("u1","password1")
    async with aiosqlite.connect(path) as db:
        await db.execute("CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,updated_at TEXT,user_id TEXT)")
        await db.execute("CREATE TABLE query_log(id TEXT PRIMARY KEY,conversation_id TEXT,raw_query TEXT,created_at TEXT,user_id TEXT)")
        await db.execute("INSERT INTO conversations(id,title,created_at,updated_at,user_id) VALUES('c','t','x','x',?)",(u.id,))
        await db.execute("INSERT INTO query_log(id,conversation_id,raw_query,created_at,user_id) VALUES('q','c','x','x',NULL)")
        await db.execute("INSERT INTO query_log(id,conversation_id,raw_query,created_at,user_id) VALUES('orphan','none','x','x',NULL)"); await db.commit()
    await s.migrate_owners(); await s.migrate_owners()
    async with aiosqlite.connect(path) as db:
        rows=await (await db.execute("SELECT id,user_id FROM query_log ORDER BY id")).fetchall()
        owners=dict(rows); assert owners['q']==u.id and owners['orphan'] != u.id
    t=await s.create_session(u.id); await s.delete_user(u.id)
    async with aiosqlite.connect(path) as db: assert await (await db.execute("SELECT COUNT(*) FROM sessions")).fetchone()==(0,)
