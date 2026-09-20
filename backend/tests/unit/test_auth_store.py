import pytest

from app.services.auth_store import AuthStore


@pytest.mark.asyncio
async def test_register_authenticate_and_session(tmp_path):
    store = AuthStore(str(tmp_path / "a.db"))
    await store.init(admin_username="admin", admin_password="admin-pass")
    user = await store.register(" Alice ", "password1")
    assert user.username == "Alice"
    assert (await store.authenticate("alice", "password1")).id == user.id
    token = await store.create_session(user.id, ttl_seconds=60)
    assert (await store.get_user_by_session(token)).id == user.id
    await store.delete_session(token)
    assert await store.get_user_by_session(token) is None


@pytest.mark.asyncio
async def test_bootstrap_idempotent_and_disabled_session(tmp_path):
    store = AuthStore(str(tmp_path / "a.db"))
    await store.init(admin_username="admin", admin_password="admin-pass")
    await store.init(admin_username="admin", admin_password="changed-pass")
    assert await store.authenticate("admin", "admin-pass")
    admin = (await store.list_users())[0]
    token = await store.create_session(admin.id)
    await store.set_active(admin.id, False)
    assert await store.get_user_by_session(token) is None

@pytest.mark.asyncio
async def test_reset_password_revokes_sessions_and_zero_ttl(tmp_path):
    store = AuthStore(str(tmp_path / "b.db")); await store.init(admin_username="admin", admin_password="admin-pass")
    user = await store.register("bob", "password1"); token = await store.create_session(user.id, ttl_seconds=0)
    assert await store.get_user_by_session(token) is None
    token2 = await store.create_session(user.id); await store.reset_password(user.id, "password2")
    assert await store.get_user_by_session(token2) is None
    token3=await store.create_session(user.id); await store.set_active(user.id,False)
    import aiosqlite
    async with aiosqlite.connect(str(tmp_path / "b.db")) as db: assert await (await db.execute("SELECT COUNT(*) FROM sessions")).fetchone()==(0,)
