# User Authentication and Admin Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add username/password registration and revocable server-side sessions, bind conversations and attachments to users, and enforce backend-only administrator access for knowledge-base import, index rebuild, feedback statistics, logs, and user management.

**Architecture:** Add an `AuthStore` backed by SQLite `users` and `sessions` tables. FastAPI dependencies resolve the current user from an HttpOnly session cookie and enforce the `admin` role; every conversation-facing query also receives an owner id. Add a small `/api/admin` surface for administrative operations, while preserving `/api/index/rebuild` as an admin-protected compatibility path. Add a Pinia auth store and minimal login/admin views without putting credentials in local storage.

**Tech Stack:** FastAPI, Pydantic v2, aiosqlite/SQLite WAL, Python `hashlib.scrypt`, Vue 3, Vue Router, Pinia, Vitest, existing SSE and attachment services.

---

## Scope and file map

The existing worktree contains unrelated uncommitted phase changes. Do not reset, clean, reformat, or include them in commits. Only the files listed below are in this plan.

### Backend files

- Create `backend/app/models/auth.py`: user/session dataclasses and request/response schemas.
- Create then modify `backend/app/services/auth_store.py`: password hashing in Task 1; user CRUD, session CRUD, bootstrap and migration in Task 2.
- Create `backend/app/api/dependencies.py`: current-user and admin FastAPI dependencies plus store injection.
- Create `backend/app/api/auth.py`: register/login/logout/me endpoints.
- Create `backend/app/api/admin.py`: user management, global feedback stats, log reading, Markdown import endpoints.
- Create `backend/app/services/knowledge_base_import.py`: safe Markdown validation and atomic writes.
- Create `backend/app/services/log_reader.py`: bounded fixed-path log reading and redaction.
- Modify `backend/app/config.py`, `backend/.env.example`, and `backend/app/main.py` for auth/bootstrap/cookie/import/log settings and lifespan wiring.
- Modify `backend/app/services/conversation_store.py`, `backend/app/services/query_log_service.py`, and `backend/app/services/feedback_service.py` for owner columns and owner-filtered operations.
- Modify `backend/app/api/conversations.py`, `attachments.py`, `chat.py`, `feedback.py`, `graph.py`, and `index.py` to declare dependencies and pass owner ids.
- Modify `backend/app/models/query_log.py` and `backend/app/models/schemas.py` for owner fields and auth/admin response models.
- Create/modify backend tests listed in the task sections below.

### Frontend files

- Create `frontend/src/api/http.ts`, `frontend/src/api/auth.ts`, and `frontend/src/api/admin.ts`.
- Create `frontend/src/stores/auth.ts`, `frontend/src/views/LoginView.vue`, and `frontend/src/views/AdminView.vue`.
- Modify `frontend/src/types/index.ts`, `frontend/src/router/index.ts`, `frontend/src/main.ts`, `frontend/src/components/AppHeader.vue`, `frontend/src/api/chat.ts`, `conversations.ts`, `attachments.ts`, `feedback.ts`, and `graph.ts`.
- Modify `frontend/src/views/GraphView.vue` so ordinary users cannot see an index-rebuild action.
- Add focused frontend tests under `frontend/src/api/__tests__`, `frontend/src/stores/__tests__`, and `frontend/src/components/__tests__`.

---

### Task 1: Add auth settings, schemas, and password/session primitives

**Files:**
- Create: `backend/app/models/auth.py`
- Create: `backend/app/services/auth_store.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/unit/test_auth_primitives.py`
- Test: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write the failing primitive tests.**

```python
# backend/tests/unit/test_auth_primitives.py
import re

from app.services.auth_store import hash_password, verify_password, hash_session_token


def test_password_hash_is_salted_and_verifiable():
    encoded = hash_password("Correct horse battery staple")
    assert encoded != "Correct horse battery staple"
    assert encoded.startswith("scrypt$")
    assert verify_password("Correct horse battery staple", encoded)
    assert not verify_password("wrong", encoded)
    assert re.fullmatch(r"scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9_-]+\$[A-Za-z0-9_-]+", encoded)


def test_session_token_hash_is_deterministic_and_not_the_token():
    token = "test-session-token"
    assert hash_session_token(token) == hash_session_token(token)
    assert hash_session_token(token) != token
```

Add settings assertions:

```python
def test_auth_settings_have_safe_defaults(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    settings = Settings(_env_file=None)
    assert settings.AUTH_COOKIE_NAME == "agent_session"
    assert settings.AUTH_SESSION_TTL_SECONDS == 7 * 24 * 60 * 60
    assert settings.AUTH_COOKIE_SECURE is False
```

- [ ] **Step 2: Run the tests and verify the expected missing-symbol failure.**

Run from `D:\Project\Agent\backend`:

```powershell
$py = (Resolve-Path '.python-runtime\cpython-3.11.16-windows-x86_64-none\python.exe').Path
$env:PYTHONPATH = (Resolve-Path '.venv\Lib\site-packages').Path
& $py -m pytest -q tests/unit/test_auth_primitives.py tests/unit/test_config.py
```

Expected: FAIL because `app.services.auth_store` and the new settings fields do not exist.

- [ ] **Step 3: Implement the minimal primitives and settings.**

Add these exact settings to `Settings`:

```python
AUTH_ADMIN_USERNAME: str = "admin"
AUTH_ADMIN_PASSWORD: str = ""
AUTH_COOKIE_NAME: str = "agent_session"
AUTH_SESSION_TTL_SECONDS: int = 7 * 24 * 60 * 60
AUTH_COOKIE_SECURE: bool = False
AUTH_PASSWORD_MIN_LENGTH: int = 8
AUTH_PASSWORD_MAX_LENGTH: int = 128
KB_IMPORT_MAX_FILE_BYTES: int = 10 * 1024 * 1024
KB_IMPORT_MAX_FILES: int = 20
LOG_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "logs")
```

In the new `auth_store.py`, define `hash_password`, `verify_password`, and `hash_session_token`. Use `secrets.token_bytes(16)` for salts, `hashlib.scrypt(..., n=2**14, r=8, p=1, dklen=32)`, URL-safe base64 without padding, and `hmac.compare_digest`. Reject passwords outside the configured inclusive bounds with `ValueError("invalid_password")`; do not create `AuthStore` methods until Task 2.

Define the public schemas in `models/auth.py`:

```python
class UserPublic(BaseModel):
    id: str
    username: str
    role: Literal["user", "admin"]
    is_active: bool
    created_at: datetime


class Credentials(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
```

- [ ] **Step 4: Run the focused tests and verify they pass.**

Expected: the primitive and settings tests pass with zero failures.

- [ ] **Step 5: Commit only the task files.**

```powershell
git add backend/app/models/auth.py backend/app/services/auth_store.py backend/app/config.py backend/tests/unit/test_auth_primitives.py backend/tests/unit/test_config.py
git commit -m "feat: add authentication primitives and settings"
```

If Git again cannot create `.git/index.lock`, request elevated permission for this exact commit; do not stage unrelated files.

### Task 2: Implement AuthStore, bootstrap, and idempotent owner migration

**Files:**
- Modify: `backend/app/models/auth.py`
- Modify: `backend/app/services/auth_store.py`
- Modify: `backend/app/services/conversation_store.py`
- Modify: `backend/app/services/query_log_service.py`
- Modify: `backend/app/models/query_log.py`
- Test: `backend/tests/unit/test_auth_store.py`
- Test: `backend/tests/unit/test_owner_migration.py`

- [ ] **Step 1: Write failing AuthStore tests.**

```python
# backend/tests/unit/test_auth_store.py
import pytest
from app.services.auth_store import AuthStore


@pytest.mark.asyncio
async def test_register_login_session_logout_and_expiry(tmp_path):
    store = AuthStore(str(tmp_path / "auth.db"), cookie_ttl_seconds=60)
    await store.init(admin_username="root", admin_password="Admin-pass-1")
    user = await store.register("alice", "User-pass-1")
    assert user.username == "alice"
    expired = await store.create_session(user.id, ttl_seconds=-1)
    assert await store.get_user_by_session(expired) is None
    token = await store.create_session(user.id)
    assert (await store.get_user_by_session(token)).id == user.id
    await store.delete_session(token)
    assert await store.get_user_by_session(token) is None


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent_and_does_not_overwrite_admin_password(tmp_path):
    store = AuthStore(str(tmp_path / "auth.db"))
    await store.init(admin_username="root", admin_password="Admin-pass-1")
    await store.init(admin_username="root", admin_password="Different-pass-2")
    assert await store.authenticate("root", "Admin-pass-1")
    assert not await store.authenticate("root", "Different-pass-2")
    assert len(await store.list_users()) == 1


@pytest.mark.asyncio
async def test_disabled_user_sessions_stop_working(tmp_path):
    store = AuthStore(str(tmp_path / "auth.db"))
    await store.init(admin_username="root", admin_password="Admin-pass-1")
    user = await store.register("alice", "User-pass-1")
    token = await store.create_session(user.id)
    await store.set_active(user.id, False)
    assert await store.get_user_by_session(token) is None
```

The migration test first creates legacy `conversations`, `messages`, and `query_log` tables without owner columns, inserts rows, then calls `AuthStore.init`; it must assert the new columns exist and both rows contain the bootstrap admin id after `migrate_owners()`.

- [ ] **Step 2: Run the tests and confirm they fail for the missing store/schema.**

Run:

```powershell
& $py -m pytest -q tests/unit/test_auth_store.py tests/unit/test_owner_migration.py
```

Expected: FAIL before implementation, not collection errors after fixing imports.

- [ ] **Step 3: Implement the SQLite schema and store API.**

`AuthStore.init()` must execute `USERS_SCHEMA_SQL` and `SESSIONS_SCHEMA_SQL`, add missing `user_id` columns to `conversations` and `query_log`, create `idx_conversations_user` and `idx_query_log_user`, ensure the configured admin exists, and then run:

```sql
UPDATE conversations SET user_id = ? WHERE user_id IS NULL;
UPDATE query_log
SET user_id = COALESCE(
    (SELECT user_id FROM conversations WHERE conversations.id = query_log.conversation_id),
    ?
)
WHERE user_id IS NULL;
```

Expose these concrete methods: `init`, `register`, `authenticate`, `create_session(user_id, ttl_seconds=None)`, `get_user_by_session`, `delete_session`, `delete_sessions_for_user`, `delete_user`, `list_users(limit=100, offset=0)`, `set_active`, `reset_password`, `count_active_admins`, and `migrate_owners`. `get_user_by_session` must reject expired sessions and inactive users; it may delete an expired row after rejecting it. Normalize usernames with `strip()` and enforce case-insensitive uniqueness using the `NOCASE` column. `delete_user` only removes the user row after the admin API has removed owned conversations and attachments.

Add `user_id: str | None = None` to `QueryLogCreate` and include it in `QueryLogStore.insert`; keep it optional so existing unit callers remain compatible. Add `user_id TEXT` to the conversation/query-log schema and migration dictionaries before creating indexes. Add `QueryLogStore.delete_by_user(user_id)` for the admin deletion flow. Keep `FeedbackStore.upsert(record, user_id=None)` optional for existing direct unit callers; the API must always pass the authenticated id.

- [ ] **Step 4: Run the focused tests and the existing store/query-log unit tests.**

```powershell
& $py -m pytest -q tests/unit/test_auth_store.py tests/unit/test_owner_migration.py tests/unit/test_store.py tests/unit/test_schemas.py
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the auth store and migration.**

```powershell
git add backend/app/models/auth.py backend/app/services/auth_store.py backend/app/services/conversation_store.py backend/app/services/query_log_service.py backend/app/models/query_log.py backend/tests/unit/test_auth_store.py backend/tests/unit/test_owner_migration.py
git commit -m "feat: persist users sessions and owner migrations"
```

### Task 3: Add current-user dependencies and authentication endpoints

**Files:**
- Create: `backend/app/api/dependencies.py`
- Create: `backend/app/api/auth.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/integration/test_api_auth.py`
- Test: `backend/tests/unit/test_auth_dependencies.py`

- [ ] **Step 1: Write failing HTTP tests.**

```python
@pytest.mark.asyncio
async def test_register_login_me_and_logout(client):
    registered = await client.post("/api/auth/register", json={"username": "alice", "password": "User-pass-1"})
    assert registered.status_code == 201
    assert registered.json()["role"] == "user"
    assert "agent_session" in registered.headers.get("set-cookie", "")
    assert (await client.get("/api/auth/me")).json()["username"] == "alice"
    await client.post("/api/auth/logout")
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_anonymous_business_api_is_rejected(client):
    assert (await client.get("/api/conversations")).status_code == 401


@pytest.mark.asyncio
async def test_duplicate_user_and_bad_credentials_are_stable(client):
    await client.post("/api/auth/register", json={"username": "alice", "password": "User-pass-1"})
    duplicate = await client.post("/api/auth/register", json={"username": "alice", "password": "Other-pass-2"})
    assert duplicate.status_code == 409
    bad = await client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"})
    assert bad.status_code == 401
```

- [ ] **Step 2: Run the tests and observe 401/missing-route failures.**

```powershell
& $py -m pytest -q tests/integration/test_api_auth.py tests/unit/test_auth_dependencies.py
```

- [ ] **Step 3: Implement dependency injection and auth routes.**

`dependencies.py` must expose `set_auth_store`, `get_auth_store`, `get_current_user`, and `require_admin`. `get_current_user` reads only `settings.AUTH_COOKIE_NAME`, raises `HTTPException(401, "未登录")` for absent/invalid sessions, and `require_admin` raises `HTTPException(403, "需要管理员权限")` for a normal user.

Each successful register/login route calls `response.set_cookie(key=settings.AUTH_COOKIE_NAME, value=token, max_age=settings.AUTH_SESSION_TTL_SECONDS, httponly=True, samesite="lax", secure=settings.AUTH_COOKIE_SECURE)`. Logout deletes the server session and calls `response.delete_cookie` with the same key and flags. `GET /api/auth/me` depends on `get_current_user`.

Mount `auth.router` before protected routers. In `lifespan`, initialize `AuthStore` after `ConversationStore` and `QueryLogStore` have created their tables, then call `set_auth_store` before yielding. Read `AUTH_ADMIN_USERNAME` and `AUTH_ADMIN_PASSWORD`; fail startup with a clear `ValueError("AUTH_ADMIN_PASSWORD is required")` when no admin exists and the password is empty. In integration fixtures, set `app.main.settings.AUTH_ADMIN_USERNAME` and `.AUTH_ADMIN_PASSWORD` directly before `LifespanManager(app)` so import-time `Settings()` construction cannot hide test values.

- [ ] **Step 4: Run auth integration tests and verify cookies are not exposed in JSON.**

Expected: registration/login/me/logout pass; anonymous `/api/conversations` returns 401; response bodies contain no `password_hash` or session token.

- [ ] **Step 5: Commit.**

```powershell
git add backend/app/api/dependencies.py backend/app/api/auth.py backend/app/main.py backend/app/models/schemas.py backend/tests/integration/test_api_auth.py backend/tests/unit/test_auth_dependencies.py
git commit -m "feat: add cookie session authentication endpoints"
```

### Task 4: Enforce owner-scoped conversation, message, attachment, chat, and feedback access

**Files:**
- Modify: `backend/app/services/conversation_store.py`
- Modify: `backend/app/services/attachment_store.py`
- Modify: `backend/app/services/query_log_service.py`
- Modify: `backend/app/services/feedback_service.py`
- Modify: `backend/app/api/conversations.py`
- Modify: `backend/app/api/attachments.py`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/api/feedback.py`
- Modify: `backend/app/api/graph.py`
- Test: `backend/tests/integration/test_api_authorization.py`
- Modify: existing integration fixtures/tests under `backend/tests/integration/`

- [ ] **Step 1: Add failing cross-user tests before changing queries.**

```python
@pytest.mark.asyncio
async def test_users_cannot_read_or_modify_each_others_conversations(client):
    alice = await register_and_login(client, "alice", "User-pass-1")
    conversation_id = (await client.post("/api/conversations", json={})).json()["id"]
    await client.post("/api/auth/logout")
    await register_and_login(client, "bob", "User-pass-2")
    assert (await client.get(f"/api/conversations/{conversation_id}")).status_code == 404
    assert (await client.patch(f"/api/conversations/{conversation_id}", json={"title": "hijack"})).status_code == 404
    assert (await client.delete(f"/api/conversations/{conversation_id}")).status_code == 404
```

Add equivalent attachment and feedback assertions, plus:

```python
assert (await client.post("/api/chat", json={"conversation_id": foreign_id, "message": "x"})).status_code == 404
assert (await client.put("/api/feedback", json={"query_log_id": foreign_log_id, "rating": "useful"})).status_code == 404
```

- [ ] **Step 2: Run the new tests and confirm they fail because current queries ignore user ids.**

```powershell
& $py -m pytest -q tests/integration/test_api_authorization.py
```

- [ ] **Step 3: Add owner-aware store methods and route dependencies.**

Extend conversation methods with optional `user_id`: when it is supplied, use `WHERE id = ? AND user_id = ?`; when it is `None`, preserve direct unit-test behavior. `create_conversation(title, user_id)` inserts the owner. `list_conversations(user_id)` filters; `get_history` joins/filter-checks the conversation. The API always supplies the authenticated id.

Add `current_user: UserPublic = Depends(get_current_user)` to conversations, attachments, chat, graph, and feedback routes. Chat must call `store.get_conversation(body.conversation_id, user_id=current_user.id)` before opening the SSE generator and pass `user_id=current_user.id` to `_write_query_log` and `QueryLogCreate`.

Add `user_id` to query-log inserts and implement `FeedbackStore.upsert(record, user_id)` with:

```sql
SELECT 1 FROM query_log WHERE id = ? AND user_id = ?
```

Return 404 for a foreign log. Keep `GET /api/feedback/stats` as a backward-compatible admin-protected endpoint and add `GET /api/admin/feedback/stats` as the canonical admin UI endpoint; both call the same store method and response model.

Attachment endpoints must call `_require_conversation(conversation_id, current_user.id, store)`. Do not add a second owner column to attachments. Graph reads require `get_current_user`; health remains unchanged.

- [ ] **Step 4: Update integration fixtures to authenticate without weakening production dependencies.**

Add this helper to `backend/tests/integration/conftest.py`:

```python
from app.main import settings

settings.AUTH_ADMIN_USERNAME = "test-admin"
settings.AUTH_ADMIN_PASSWORD = "Admin-pass-1"


async def login_admin(client):
    response = await client.post("/api/auth/login", json={"username": "test-admin", "password": "Admin-pass-1"})
    assert response.status_code == 200, response.text
```

Set the `app.main.settings.AUTH_ADMIN_USERNAME` and `.AUTH_ADMIN_PASSWORD` values before app lifespan creation and call `await login_admin(c)` in the existing client fixtures and manual attachment/chat clients. Add `register_and_login` for two-user tests. Do not add a production-only test bypass or dependency override.

- [ ] **Step 5: Run the full backend integration suite.**

```powershell
& $py -m pytest -q tests/integration
```

Expected: all integration tests pass, including existing SSE and attachment tests, with new 401/404 cross-user coverage.

- [ ] **Step 6: Commit owner enforcement.**

```powershell
git add backend/app/services backend/app/api backend/tests/integration
git commit -m "feat: scope business data to authenticated users"
```

### Task 5: Add administrator user management, logs, and Markdown import

**Files:**
- Create: `backend/app/api/admin.py`
- Create: `backend/app/services/knowledge_base_import.py`
- Create: `backend/app/services/log_reader.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/index.py`
- Modify: `backend/app/models/schemas.py`
- Test: `backend/tests/unit/test_knowledge_base_import.py`
- Test: `backend/tests/unit/test_log_reader.py`
- Test: `backend/tests/integration/test_api_admin.py`

- [ ] **Step 1: Write failing unit and HTTP tests.**

```python
def test_import_rejects_path_traversal_and_non_markdown(tmp_path):
    service = KnowledgeBaseImportService(tmp_path, max_file_bytes=100, max_files=2)
    with pytest.raises(ImportValidationError, match="markdown_only"):
        service.validate("notes.txt", b"x")
    with pytest.raises(ImportValidationError, match="unsafe_filename"):
        service.validate("..\\outside.md", b"# x")


def test_log_reader_limits_lines_and_redacts_secrets(tmp_path):
    (tmp_path / "app.log").write_text("x" * 5000 + "\npassword=secret token=abc", encoding="utf-8")
    result = LogReader(tmp_path).read(limit=2, max_line_length=80)
    assert len(result) == 2
    assert "secret" not in result[0]
    assert "[REDACTED]" in result[0]
    assert all(len(line) <= 80 for line in result)
```

Add integration assertions that a normal user receives 403 for every admin route, while an admin can list users, disable/reset/delete a normal user, read stats/logs, import a Markdown file, and call `/api/index/rebuild`. Assert the last-admin guard returns 409/422 and never removes the final administrator.

- [ ] **Step 2: Run tests and confirm the new symbols/routes are absent.**

```powershell
& $py -m pytest -q tests/unit/test_knowledge_base_import.py tests/unit/test_log_reader.py tests/integration/test_api_admin.py
```

- [ ] **Step 3: Implement safe import and log reader services.**

`KnowledgeBaseImportService` must reject names whose normalized `Path(name).name` differs from the supplied name, names containing `..` or either slash character, empty names, non-`.md` suffixes, duplicate names in one batch, files over `KB_IMPORT_MAX_FILE_BYTES`, and batches over `KB_IMPORT_MAX_FILES`. Write each file to `data_dir / safe_name + ".tmp-<uuid>"`, flush/fsync, then `os.replace`; remove a failed temporary file.

`LogReader.read(limit=100, max_line_length=4000)` must clamp `limit` to 1–500, read only `app.log` and `app.log.N` files under the configured log directory, return newest lines first, truncate each line, and replace values matching `(?i)(password|token|api[_-]?key)=\S+` with `\1=[REDACTED]`.

- [ ] **Step 4: Implement admin routes and deletion orchestration.**

Use `require_admin` on every handler. User responses must be `UserPublic` only. Disable/reset password calls `AuthStore.delete_sessions_for_user`. Deleting a normal user must first list that user's conversations, call `AttachmentStore.delete_conversation_attachments`, call `ConversationStore.delete_conversation` for each, delete user query logs, and finally delete the user. Reject deletion or deactivation when `count_active_admins()` would become zero.

The import handler resolves `resolve_kb_profile().data_dir`, consumes repeated `files` multipart fields, and returns `{count, files}`. It never calls `indexer.build`; `/api/index/rebuild` remains a separate operation. Protect the existing rebuild handler with `require_admin` and preserve its lock and response model.

- [ ] **Step 5: Run the admin tests and backend compile check.**

```powershell
& $py -m pytest -q tests/unit/test_knowledge_base_import.py tests/unit/test_log_reader.py tests/integration/test_api_admin.py
& $py -m compileall -q app
```

Expected: zero test failures and compileall exit code 0.

- [ ] **Step 6: Commit admin capabilities.**

```powershell
git add backend/app/api/admin.py backend/app/services/knowledge_base_import.py backend/app/services/log_reader.py backend/app/main.py backend/app/api/index.py backend/app/models/schemas.py backend/tests/unit/test_knowledge_base_import.py backend/tests/unit/test_log_reader.py backend/tests/integration/test_api_admin.py
git commit -m "feat: add administrator management and knowledge-base controls"
```

### Task 6: Add frontend authenticated transport and auth store

**Files:**
- Create: `frontend/src/api/http.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/stores/auth.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/chat.ts`, `conversations.ts`, `attachments.ts`, `feedback.ts`, `graph.ts`
- Test: `frontend/src/api/__tests__/auth.test.ts`
- Test: `frontend/src/stores/__tests__/auth.test.ts`
- Modify: existing frontend API tests for credentials

- [ ] **Step 1: Write failing transport/store tests.**

```ts
it('sends credentials and exposes a structured 401 error', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: '未登录' }), { status: 401 })))
  await expect(apiFetch('/api/conversations')).rejects.toMatchObject({ status: 401 })
  expect(fetch).toHaveBeenCalledWith('/api/conversations', expect.objectContaining({ credentials: 'include' }))
})

it('loads the current user only once', async () => {
  const store = useAuthStore()
  await store.ensureLoaded()
  await store.ensureLoaded()
  expect(fetch).toHaveBeenCalledTimes(1)
})
```

- [ ] **Step 2: Run the focused frontend tests and observe missing-module failures.**

```powershell
Set-Location D:\Project\Agent\frontend
npm test -- --run src/api/__tests__/auth.test.ts src/stores/__tests__/auth.test.ts
```

- [ ] **Step 3: Implement the shared transport and auth API/store.**

`apiFetch` must merge `credentials: 'include'`, parse JSON error detail, throw an `ApiError(status, detail)`, and dispatch a single `auth-expired` browser event for 401 responses. `auth.ts` exposes `register`, `login`, `logout`, and `me`. The Pinia store keeps only `user`, `loaded`, and `loading`; `ensureLoaded` is idempotent and never stores a token.

Update every existing fetch/XHR call to use `apiFetch` or `credentials: 'include'`; set `xhr.withCredentials = true` in `uploadAttachments`; pass `credentials: 'include'` to `streamChat` and preserve its AbortController behavior.

- [ ] **Step 4: Run all frontend API/store tests and verify the existing tests still pass.**

```powershell
npm test -- --run src/api src/stores
```

Expected: all selected tests pass with no unhandled auth-expired event errors.

- [ ] **Step 5: Commit frontend transport.**

```powershell
git add frontend/src/api frontend/src/stores/auth.ts frontend/src/types/index.ts frontend/src/api/__tests__ frontend/src/stores/__tests__
git commit -m "feat: add frontend cookie-auth transport"
```

### Task 7: Add login routing, header session controls, and admin UI

**Files:**
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/src/views/AdminView.vue`
- Create: `frontend/src/api/admin.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/components/AppHeader.vue`
- Modify: `frontend/src/views/GraphView.vue`
- Test: `frontend/src/components/__tests__/LoginView.test.ts`
- Test: `frontend/src/stores/__tests__/auth.test.ts`

- [ ] **Step 1: Write failing component/router behavior tests.**

```ts
it('submits registration and shows the authenticated user', async () => {
  const wrapper = mount(LoginView, { global: { plugins: [createPinia()] } })
  await wrapper.get('[name="username"]').setValue('alice')
  await wrapper.get('[name="password"]').setValue('User-pass-1')
  await wrapper.get('form').trigger('submit')
  expect(useAuthStore().user?.username).toBe('alice')
})
```

Add a router test that `/admin` redirects a normal user to `/chat`, and an `auth-expired` event clears the store.

- [ ] **Step 2: Run the focused tests and confirm the views/routes are missing.**

```powershell
npm test -- --run src/components/__tests__/LoginView.test.ts src/stores/__tests__/auth.test.ts
```

- [ ] **Step 3: Implement the minimal views and guards.**

Add routes:

```ts
{ path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
{ path: '/admin', name: 'admin', component: () => import('@/views/AdminView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
```

Register a `router.beforeEach` guard that awaits `auth.ensureLoaded()`, redirects unauthenticated protected routes to `/login?redirect=<encoded path>`, and redirects non-admin users away from `/admin`. `main.ts` must install Pinia before mounting so the guard can use the store.

`LoginView.vue` has one form toggling between login/register, fields named `username` and `password`, an error paragraph, and a submit button. On success navigate to the validated redirect or `/chat`. `AppHeader.vue` shows username, a logout button, and an admin link only when `auth.isAdmin` is true. `GraphView.vue` keeps graph reading for all logged-in users but hides its rebuild button unless the current role is admin.

`AdminView.vue` uses `admin.ts` to render user rows and four small panels: user actions, feedback stats, recent logs, and Markdown import/rebuild. It displays backend errors verbatim only as bounded messages and never renders password hashes.

- [ ] **Step 4: Run frontend tests and production build.**

```powershell
npm test -- --run
npm run build
```

Expected: all tests pass and `vue-tsc`/Vite exit 0.

- [ ] **Step 5: Commit frontend views and routing.**

```powershell
git add frontend/src/views frontend/src/router/index.ts frontend/src/main.ts frontend/src/components/AppHeader.vue frontend/src/api/admin.ts frontend/src/components/__tests__/LoginView.test.ts
git commit -m "feat: add login and administrator views"
```

### Task 8: Full regression, security audit, and completion evidence

**Files:**
- Modify only tests/fixtures or docs when a verified failure requires it; do not perform unrelated refactors.

- [ ] **Step 1: Run backend unit and integration suites with the project runtime.**

```powershell
Set-Location D:\Project\Agent\backend
$py = (Resolve-Path '.python-runtime\cpython-3.11.16-windows-x86_64-none\python.exe').Path
$env:PYTHONPATH = (Resolve-Path '.venv\Lib\site-packages').Path
& $py -m pytest -q
```

Record the exact passed/failed/skipped counts. If an integration test hangs, keep the production lifespan unchanged and patch only the existing integration fixture as documented in `backend/tests/integration/conftest.py`.

- [ ] **Step 2: Run compile, frontend tests/build, and diff hygiene.**

```powershell
& $py -m compileall -q app eval tests
Set-Location D:\Project\Agent\frontend
npm test -- --run
npm run build
Set-Location D:\Project\Agent
git diff --check
```

- [ ] **Step 3: Perform a route/permission checklist against live test clients.**

Verify all of the following with fresh HTTP calls: anonymous `/api/health` is 200; anonymous `/api/conversations`, `/api/chat`, `/api/graph`, `/api/feedback`, and `/api/index/rebuild` are 401; a normal user gets 403 from every `/api/admin/**` route and `/api/index/rebuild`; an admin can perform each required administrative operation; two users cannot cross-read or mutate conversations, attachments, logs, or feedback; disabling a user invalidates an already-issued cookie.

- [ ] **Step 4: Inspect the final diff and ensure only scoped files are staged.**

```powershell
git status --short
git diff --stat HEAD
git diff --check HEAD
```

Do not claim completion until the commands above have fresh exit-code/output evidence and unrelated pre-existing changes remain untouched.
