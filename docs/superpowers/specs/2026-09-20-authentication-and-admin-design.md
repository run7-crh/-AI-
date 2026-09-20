# 用户登录与管理员权限设计

日期：2026-09-20

## 目标

为现有无人机售后 Agent 增加可撤销的用户登录、会话/附件归属和管理员能力，同时保持现有聊天 SSE、附件临时上下文、反馈绑定和知识库索引行为。后端鉴权是最终安全边界，前端登录页和管理员按钮只负责用户体验。

## 已确认的约束与假设

- 普通用户可以自助注册。
- 账号标识是唯一用户名，不引入邮箱验证、OAuth、短信登录或多租户。
- 登录采用用户名 + 密码；密码只保存不可逆哈希。
- 浏览器使用服务端随机会话 Cookie；服务端只保存 session token 的 SHA-256 哈希。
- 会话固定有效期 7 天，不做滑动续期；登出删除会话，禁用用户删除该用户的全部会话。
- 管理员首个账号由 `ADMIN_USERNAME` 与 `ADMIN_PASSWORD` 环境变量幂等初始化；初始化不会覆盖已有账号。
- 旧 SQLite 数据统一归属首个管理员，迁移不删除现有记录。
- 知识库导入第一版只接收一个或多个 Markdown 文件；导入和索引重建是两个明确操作。
- 健康检查保持匿名，图谱读取要求登录；其余业务 API 至少要求登录。
- 管理员拥有独立 `admin` 角色，但管理员自己的聊天数据仍按普通会话规则隔离；跨用户审计只通过明确的管理 API 暴露。

## 架构

采用显式依赖注入，而不是依赖全局认证中间件白名单：

1. `AuthStore` 负责用户、会话、密码哈希、初始化和迁移。
2. `get_current_user` 依赖读取 HttpOnly Cookie、校验 session、确认用户仍启用；`require_admin` 在此基础上检查角色。
3. 业务路由显式声明依赖；服务层接收 `user_id` 并按所有权过滤，避免只保护路由而留下 IDOR。
4. 管理路由集中在 `/api/admin`，索引重建兼容现有 `/api/index/rebuild` 但增加管理员依赖。
5. 前端使用 Pinia auth store 恢复 `/api/auth/me`，路由守卫保护聊天、图谱和管理页；Cookie 不进入 localStorage。

## 数据模型与迁移

### 新表

```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
```

### 既有表迁移

- `conversations` 增加可空 `user_id` 与索引。认证后的新会话必须写入当前用户；启动迁移把已有 NULL 值更新为首个管理员 ID。
- `query_log` 增加可空 `user_id` 与索引。聊天写入时使用会话所属用户；迁移按 `conversation_id` 回填，找不到会话的孤立日志归管理员。
- `attachments` 不增加重复 owner 字段，继续通过 `conversation_id` 继承会话所有权。
- `messages` 不增加 owner 字段，继续通过会话外键继承所有权。
- 迁移顺序固定为：创建用户表并确保管理员存在 → 创建 session 表 → 建立/补充业务表列 → 回填旧记录 → 创建依赖新列的索引。所有步骤可重复执行。

### 密码与会话格式

- 密码使用标准库 `hashlib.scrypt`，随机 salt，保存算法与参数前缀、salt 和 digest；校验使用 `hmac.compare_digest`。
- 注册和管理员创建/重置密码要求长度 8–128 个字符；登录错误不区分“用户不存在”和“密码错误”。
- Cookie 名称配置为 `agent_session`；值是 `secrets.token_urlsafe(32)`，数据库仅保存 SHA-256(token)。
- Cookie 属性：`HttpOnly=True`、`SameSite=Lax`、`Max-Age=604800`；`Secure` 由 `AUTH_COOKIE_SECURE` 配置控制。

## API 与权限

### 匿名认证 API

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/api/auth/register` | 创建普通用户并建立会话 |
| POST | `/api/auth/login` | 校验凭据并建立会话 |
| POST | `/api/auth/logout` | 删除当前会话并清理 Cookie |
| GET | `/api/auth/me` | 返回当前用户；无会话返回 401 |

注册和登录成功返回 `{id, username, role}`。用户名冲突返回稳定的 409；无效凭据返回 401；禁用账号不能登录。

### 管理 API

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/admin/users` | 分页/限量列出用户，不返回密码哈希 |
| POST | `/api/admin/users` | 管理员创建普通用户 |
| PATCH | `/api/admin/users/{id}/status` | 启用/禁用用户并使其会话失效 |
| POST | `/api/admin/users/{id}/password` | 重置密码并使其会话失效 |
| DELETE | `/api/admin/users/{id}` | 删除普通用户及其会话、会话数据和附件 |
| GET | `/api/admin/feedback/stats` | 查看全局反馈统计 |
| GET | `/api/admin/logs` | 读取固定日志目录的有限行数 |
| POST | `/api/admin/knowledge-base/import` | 上传 Markdown 到当前知识库目录 |

管理员不能通过删除/降级操作移除最后一个管理员；管理员修改自身密码是允许的。

### 既有 API 的鉴权/所有权

- `/api/health` 保持匿名。
- `/api/conversations/**`、`/api/chat`、`/api/conversations/**/attachments`、`PUT /api/feedback`、`GET /api/graph` 要求登录。
- `/api/index/rebuild` 要求管理员；现有路径保留以兼容调用方。
- 会话、附件和聊天先按当前用户查询；资源不属于当前用户时统一返回 404，避免泄露资源存在性。
- 反馈提交先检查 `query_log.user_id` 与当前用户一致；统计接口移至管理员依赖。
- 前端隐藏管理员入口不作为授权手段。

## 知识库导入与日志读取

- 导入服务只接受 `.md` 扩展名；文件名经过 `Path(...).name` 规范化，拒绝空名、路径分隔符、`..` 和超出大小限制的文件。
- 文件写入 `resolve_kb_profile().data_dir` 下的受控目录，采用临时文件 + 原子替换；导入失败不触发索引重建。
- 管理员随后显式调用 `/api/index/rebuild`，沿用现有互斥锁、候选 collection 和图谱构建流程。
- 日志 API 只允许读取应用固定日志文件及轮转文件，参数限制最大行数和单行长度；返回前脱敏 Cookie、密码字段、API key 等敏感模式。

## 前端流程

- 新增 `auth` API/store 与登录/注册视图；登录和注册共用表单，成功后跳转原目标路由或 `/chat`。
- `router` 对聊天、图谱和管理页做登录守卫；管理页再检查 `role=admin`。
- 所有 fetch、SSE 和附件 XHR 显式携带 credentials；收到 401 时清空 auth store 并跳转登录。
- Header 显示当前用户名和登出操作；管理员显示管理入口。
- 管理页提供用户表格、启用/禁用、重置密码、删除普通用户、反馈统计、日志查看、Markdown 导入和索引重建的最小操作界面，不新增复杂 UI 框架。

## 错误与安全策略

- 未登录统一 401，已登录但非管理员统一 403；资源越权统一 404。
- 不在响应、前端状态或日志中暴露密码哈希、session token、附件正文或 API key。
- Cookie 会话不使用 localStorage；CORS 继续使用显式来源列表并允许 credentials。
- 禁用或删除用户后，现有会话立即失效；过期 session 在校验时拒绝并可清理。
- 不在本阶段加入 CSRF token、OAuth、短信、邮箱找回、多租户或细粒度管理员权限。

## 测试策略

按 TDD 先写失败测试，再实现最小行为：

1. `AuthStore` 单元测试：密码哈希不可逆、注册唯一性、登录/登出、过期与禁用 session、管理员幂等初始化。
2. 迁移单元测试：旧库补列、旧会话/日志归管理员、重复初始化不重复创建且不覆盖管理员密码。
3. 集成鉴权测试：匿名 401、普通用户 403、跨用户会话/附件/聊天/query log/反馈 404、管理员 API 成功。
4. 导入/日志测试：非 Markdown、路径穿越、大小限制、固定路径、脱敏和行数限制。
5. 回归现有 integration/unit 测试；继续只在测试 fixture 中隔离 reranker/indexer/graph 的昂贵启动，不改变生产 lifespan。
6. 前端测试覆盖 auth store、路由守卫、401 处理、管理员视图关键操作，并运行现有构建。

## 非目标

- 不实现 OAuth、短信、邮箱验证/找回、JWT 刷新、多租户、细粒度 RBAC、在线客服工单或部署/TLS。
- 不重构 LangGraph、RAG、Chroma 数据结构；索引构建仍由现有 Indexer 负责。

## 验收标准

- 所有受保护 API 在没有有效 session 时由后端拒绝。
- 普通用户无法读取或修改另一用户的会话、附件、聊天上下文和反馈。
- 只有管理员可以导入 Markdown、重建索引、查看统计/日志和管理用户。
- 首次启动与重复启动均能安全初始化管理员并迁移旧数据。
- 既有 SSE、附件和健康检查回归测试通过，后端编译/测试和前端测试/构建通过。
