import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
import aiosqlite
from app.models.auth import UserPublic
_SALT_BYTES = 16
_KEY_BYTES = 32


def _validate_password(password: str) -> None:
    from app.config import settings
    if not isinstance(password, str) or not (settings.AUTH_PASSWORD_MIN_LENGTH <= len(password) <= settings.AUTH_PASSWORD_MAX_LENGTH):
        raise ValueError("invalid_password")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    if not value or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    _validate_password(password)
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=_KEY_BYTES)
    return f"scrypt$16384$8$1${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _validate_password(password)
        if not isinstance(encoded, str):
            return False
        scheme, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$")
        if scheme != "scrypt" or (n_text, r_text, p_text) != ("16384", "8", "1"):
            return False
        salt = _decode(salt_text)
        expected = _decode(digest_text)
        if len(salt) != _SALT_BYTES or len(expected) != _KEY_BYTES:
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=_KEY_BYTES)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError, UnicodeError):
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

class AuthStore:
    def __init__(self, db_path: str):
        self.db_path = db_path; Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def init(self, admin_username=None, admin_password=None):
        from app.config import settings
        admin_username = (admin_username or settings.AUTH_ADMIN_USERNAME).strip()
        admin_password = settings.AUTH_ADMIN_PASSWORD if admin_password is None else admin_password
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.executescript("""CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','admin')), is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_login_at TEXT); CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, expires_at TEXT NOT NULL); CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id); CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);""")
            for table in ("conversations", "query_log"):
                exists = await (await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,))).fetchone()
                if exists:
                    cols = {r[1] for r in await (await db.execute(f"PRAGMA table_info({table})")).fetchall()}
                    if "user_id" not in cols: await db.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")
                    await db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)")
            now = datetime.now(timezone.utc).isoformat()
            row = await (await db.execute("SELECT id FROM users WHERE username=?", (admin_username,))).fetchone()
            if not row and admin_password:
                await db.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)", (secrets.token_hex(16), admin_username, hash_password(admin_password), "admin", 1, now, now, None))
            await db.commit()
        await self.migrate_owners()

    def _public(self, row):
        return UserPublic(id=row[0], username=row[1], role=row[3], is_active=bool(row[4]), created_at=row[5])

    async def register(self, username, password, role="user"):
        username = username.strip()
        if not username or len(username)>64 or role not in ("user","admin"): raise ValueError("invalid_user")
        now=datetime.now(timezone.utc).isoformat(); uid=secrets.token_hex(16)
        async with aiosqlite.connect(self.db_path) as db:
            try: await db.execute("INSERT INTO users VALUES(?,?,?,?,?,?,?,?)", (uid,username,hash_password(password),role,1,now,now,None)); await db.commit()
            except aiosqlite.IntegrityError: raise ValueError("username_taken")
        return UserPublic(id=uid, username=username, role=role, is_active=True, created_at=now)

    async def authenticate(self, username, password):
        async with aiosqlite.connect(self.db_path) as db:
            row=await (await db.execute("SELECT * FROM users WHERE username=?", (username.strip(),))).fetchone()
            if not row or not row[4] or not verify_password(password,row[2]): return None
            now=datetime.now(timezone.utc).isoformat(); await db.execute("UPDATE users SET last_login_at=?,updated_at=? WHERE id=?",(now,now,row[0])); await db.commit(); return self._public(row)

    async def create_session(self,user_id,ttl_seconds=None):
        from app.config import settings
        token=secrets.token_urlsafe(32); now=datetime.now(timezone.utc); exp=now+timedelta(seconds=settings.AUTH_SESSION_TTL_SECONDS if ttl_seconds is None else ttl_seconds)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            row=await (await db.execute("SELECT is_active FROM users WHERE id=?",(user_id,))).fetchone()
            if not row or not row[0]: raise ValueError("user_inactive")
            await db.execute("INSERT INTO sessions VALUES(?,?,?,?,?)",(secrets.token_hex(16),user_id,hash_session_token(token),now.isoformat(),exp.isoformat())); await db.commit()
        return token

    async def get_user_by_session(self,token):
        if not isinstance(token,str): return None
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("DELETE FROM sessions WHERE expires_at<=?",(datetime.now(timezone.utc).isoformat(),))
            await db.commit()
            row=await (await db.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=1",(hash_session_token(token),datetime.now(timezone.utc).isoformat()))).fetchone(); return self._public(row) if row else None
    async def delete_session(self,token):
        async with aiosqlite.connect(self.db_path) as db: await db.execute("PRAGMA foreign_keys=ON"); await db.execute("DELETE FROM sessions WHERE token_hash=?",(hash_session_token(token),)); await db.commit()
    async def set_active(self,user_id,active):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("UPDATE users SET is_active=?, updated_at=? WHERE id=?",(int(active),datetime.now(timezone.utc).isoformat(),user_id))
            await db.commit()
        if not active: await self.delete_sessions_for_user(user_id)

    async def get_user(self, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            row = await (await db.execute("SELECT * FROM users WHERE id=?", (user_id,))).fetchone()
            return self._public(row) if row else None
    async def list_users(self,limit=100,offset=0):
        async with aiosqlite.connect(self.db_path) as db: await db.execute("PRAGMA foreign_keys=ON"); return [self._public(r) for r in await (await db.execute("SELECT * FROM users ORDER BY created_at LIMIT ? OFFSET ?",(limit,offset))).fetchall()]
    async def delete_sessions_for_user(self,user_id):
        async with aiosqlite.connect(self.db_path) as db: await db.execute("PRAGMA foreign_keys=ON"); await db.execute("DELETE FROM sessions WHERE user_id=?",(user_id,)); await db.commit()
    async def delete_user(self,user_id):
        async with aiosqlite.connect(self.db_path) as db: await db.execute("PRAGMA foreign_keys=ON"); await db.execute("DELETE FROM users WHERE id=?",(user_id,)); await db.commit()
    async def count_active_admins(self):
            async with aiosqlite.connect(self.db_path) as db: await db.execute("PRAGMA foreign_keys=ON"); return (await (await db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1")).fetchone())[0]

    async def reset_password(self,user_id,password):
        async with aiosqlite.connect(self.db_path) as db: await db.execute("PRAGMA foreign_keys=ON"); await db.execute("UPDATE users SET password_hash=?,updated_at=? WHERE id=?",(hash_password(password),datetime.now(timezone.utc).isoformat(),user_id)); await db.execute("DELETE FROM sessions WHERE user_id=?",(user_id,)); await db.commit()

    async def migrate_owners(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON")
            row=await (await db.execute("SELECT id FROM users WHERE role='admin' ORDER BY created_at LIMIT 1")).fetchone()
            if not row: return
            uid=row[0]
            for table in ("conversations","query_log"):
                exists=await (await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,))).fetchone()
                if not exists: continue
                cols={r[1] for r in await (await db.execute(f"PRAGMA table_info({table})")).fetchall()}
                if "user_id" not in cols: await db.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT")
                await db.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user ON {table}(user_id)")
            if await (await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversations'")).fetchone(): await db.execute("UPDATE conversations SET user_id=? WHERE user_id IS NULL",(uid,))
            if await (await db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='query_log'")).fetchone(): await db.execute("UPDATE query_log SET user_id=COALESCE((SELECT user_id FROM conversations WHERE conversations.id=query_log.conversation_id), ?) WHERE user_id IS NULL",(uid,))
            await db.commit()
