# 售后 Agent 工单闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有无人机售后 Agent 中，为一个无人机商家/品牌实现用户建单、品牌管理员处理、用户确认解决/重开以及附件证据留存的完整工单闭环。

**Architecture:** 在现有 FastAPI + SQLite + Vue + Cookie 会话架构上新增独立的 TicketStore 和工单 API。当前是单商家单品牌部署，知识库、工单队列和管理员操作都属于该品牌，不增加 `tenant_id` 或多租户抽象。会话、消息、query log 和附件仍由原有存储负责，工单只保存业务快照、状态和引用关系；状态转换集中在服务层校验，Agent 只生成草稿和建议，品牌管理员和用户通过明确动作推进状态。

**Tech Stack:** FastAPI、Pydantic、aiosqlite、SQLite WAL、Vue 3、Pinia、Vue Router、Vitest、pytest/httpx。

---

## 文件边界

### 新建文件

- `backend/app/models/ticket.py`：工单状态、优先级、事件、证据和公开响应模型。
- `backend/app/services/ticket_store.py`：`tickets`、`ticket_events`、`ticket_evidence` 表的初始化、迁移和 CRUD。
- `backend/app/services/ticket_service.py`：从会话生成草稿、幂等建单、状态转换、事件审计和证据提升编排。
- `backend/app/api/tickets.py`：普通用户工单 API。
- `backend/app/api/admin_tickets.py`：管理员工单队列、详情和处理 API。
- `backend/tests/unit/test_ticket_store.py`：存储、迁移、状态转换和幂等单测。
- `backend/tests/unit/test_ticket_service.py`：会话快照、证据提升和安全规则单测。
- `backend/tests/integration/test_api_tickets.py`：用户/管理员 API 和所有权集成测试。
- `frontend/src/api/tickets.ts`：用户工单 API 客户端。
- `frontend/src/api/adminTickets.ts`：管理员工单 API 客户端。
- `frontend/src/stores/tickets.ts`：用户工单列表、详情和动作状态。
- `frontend/src/views/TicketsView.vue`：用户“我的工单”列表。
- `frontend/src/views/TicketDetailView.vue`：用户工单详情、补充资料和确认解决。
- `frontend/src/components/TicketDraftCard.vue`：聊天页建单草稿确认卡片。
- `frontend/src/components/TicketTimeline.vue`：公开状态时间线。
- `frontend/src/components/AdminTicketQueue.vue`：管理员队列和筛选。
- `frontend/src/components/AdminTicketDetail.vue`：管理员工单详情和操作区。
- `frontend/src/api/__tests__/tickets.test.ts`、`frontend/src/stores/__tests__/tickets.test.ts`：客户端和 store 测试。
- `frontend/src/components/__tests__/TicketDraftCard.test.ts`、`frontend/src/components/__tests__/TicketTimeline.test.ts`：组件测试。

### 修改文件

- `backend/app/main.py`：初始化 `TicketStore`、注入路由和生命周期。
- `backend/app/models/schemas.py`：仅在需要兼容既有会话响应时增加工单摘要类型，不把工单字段塞进消息模型。
- `backend/app/services/attachment_store.py`：增加附件提升为工单证据的原子操作，并让清理任务跳过已绑定工单的附件。
- `backend/app/api/attachments.py`：保留现有会话附件 API；不新增绕过工单权限的下载接口。
- `frontend/src/router/index.ts`：增加用户工单列表/详情和管理员工单入口。
- `frontend/src/types/index.ts`：增加工单、事件、证据和状态类型。
- `frontend/src/views/ChatView.vue`、`frontend/src/components/AssistantMessage.vue`：在满足升级条件时显示建单入口并打开草稿卡片。
- `frontend/src/views/AdminView.vue`：挂载管理员工单队列入口，不重写已有用户、日志、知识库功能。
- `backend/tests/integration/conftest.py`：为工单集成测试提供同一 SQLite 生命周期和管理员登录 fixture。
- `README.md`：补充已实现的第一阶段工单能力和仍未实现的外部 CRM 对接。

### 第一阶段商家边界

- 当前部署只服务一个无人机商家/品牌。
- 现有 `admin` 账号就是该品牌的售后主管/处理人员。
- 当前知识库、工单队列、SLA 配置和售后规则不带商家选择器。
- 不增加 `tenant_id`、商家注册、员工邀请或跨商家隔离字段。
- 未来多商家化必须单独设计租户迁移、知识库隔离和权限模型，不在本计划内。

## 状态和权限约束

状态常量固定为：`draft`、`submitted`、`assigned`、`in_progress`、`waiting_user`、`resolved_pending_confirm`、`closed`、`reopened`、`cancelled`。

允许的状态转换集中在 `ticket_service.py`，任何 API 不得自行拼接 SQL 修改状态：

```python
ALLOWED_TRANSITIONS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"assigned", "waiting_user", "cancelled"},
    "assigned": {"in_progress", "waiting_user", "cancelled"},
    "in_progress": {"waiting_user", "resolved_pending_confirm", "cancelled"},
    "waiting_user": {"in_progress", "cancelled"},
    "resolved_pending_confirm": {"closed", "reopened"},
    "reopened": {"assigned", "in_progress", "waiting_user"},
    "closed": set(),
    "cancelled": set(),
}
```

普通用户只能读取自己的工单、提交草稿、补充公开消息、确认解决和重开；单商家范围内的管理员使用 `require_admin` 读取全部工单并执行接单、转派、内部备注、公开回复和处理状态变更；Agent 和系统只能通过服务层写入建议或审计事件。跨用户资源统一返回 404。

## Task 1: 建立工单领域模型和 SQLite 存储

**Files:**

- Create: `backend/app/models/ticket.py`
- Create: `backend/app/services/ticket_store.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_ticket_store.py`

- [ ] **Step 1: 写失败的存储测试**

覆盖以下行为：初始化创建三张表；重复 `init()` 不破坏数据；创建工单自动生成唯一 `ticket_number`；事件只追加；证据关系使用唯一约束；按用户列出工单；按管理员列出全部工单。

```python
@pytest.mark.asyncio
async def test_ticket_store_init_and_idempotent_create(tmp_path):
    store = TicketStore(str(tmp_path / "tickets.db"))
    await store.init()
    await store.init()
    ticket = await store.create_ticket({
        "user_id": "u1", "conversation_id": "c1",
        "title": "遥控器无法连接", "status": "draft",
        "priority": "normal", "safety_level": "none",
    })
    assert ticket["ticket_number"].startswith("T-")
    assert await store.get_ticket(ticket["id"], user_id="u1")
    assert await store.get_ticket(ticket["id"], user_id="u2") is None
```

- [ ] **Step 2: 运行单测确认失败**

运行：`pytest -q backend/tests/unit/test_ticket_store.py`（使用项目约定的 bundled Python 和 `PYTHONPATH`）。

预期：因 `TicketStore` 和模型尚未存在而失败。

- [ ] **Step 3: 实现最小领域模型和 schema**

在 `ticket.py` 定义 `TicketStatus`、`TicketPriority`、`TicketActorType`、`TicketResponse`、`TicketEventResponse`、`TicketEvidenceResponse`，并在 `ticket_store.py` 使用 `tickets`、`ticket_events`、`ticket_evidence` 三张表。主表至少包含 `id`、`ticket_number`、`user_id`、`conversation_id`、`title`、`problem_summary`、设备字段、`priority`、`safety_level`、`assignee_user_id`、`status`、处理结果和时间字段，并对 `(user_id, conversation_id)` 建唯一约束。

- [ ] **Step 4: 将 TicketStore 注入应用生命周期**

在 `main.py` 增加 `_ticket_store`、`get_ticket_store()` 和 lifespan 初始化，使用与 `ConversationStore` 相同的 `TEST_SQLITE_PATH`。路由依赖通过 `tickets.set_store()` 和 `admin_tickets.set_store()` 注入，不在 API 模块中创建数据库连接。

- [ ] **Step 5: 运行单测确认通过**

运行：`pytest -q backend/tests/unit/test_ticket_store.py`。

预期：表初始化、用户隔离、唯一约束和事件追加测试全部通过。

- [ ] **Step 6: 提交独立变更**

```bash
git add backend/app/models/ticket.py backend/app/services/ticket_store.py backend/app/main.py backend/tests/unit/test_ticket_store.py
git commit -m "feat: add ticket persistence model"
```

## Task 2: 实现工单业务服务、状态机和会话快照

**Files:**

- Create: `backend/app/services/ticket_service.py`
- Modify: `backend/app/services/ticket_store.py`
- Test: `backend/tests/unit/test_ticket_service.py`

- [ ] **Step 1: 写失败的服务测试**

使用 fake conversation store、query log store 和 attachment store，验证从会话生成问题摘要；安全等级和升级原因取自服务端消息/query log；同一用户和会话重复建单返回同一工单；高风险工单不能被系统关闭。

```python
@pytest.mark.asyncio
async def test_create_draft_is_idempotent_and_keeps_server_safety_data():
    service = TicketService(
        ticket_store=ticket_store,
        conversation_store=conversation_store,
        query_log_store=query_log_store,
        attachment_store=attachment_store,
    )
    first = await service.create_draft_from_conversation("u1", "c1", actor_type="user")
    second = await service.create_draft_from_conversation("u1", "c1", actor_type="user")
    assert first["id"] == second["id"]
    assert first["safety_level"] == "high"
    assert first["escalation_reason"]
```

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest -q backend/tests/unit/test_ticket_service.py`。

预期：因业务服务和状态转换尚未实现而失败。

- [ ] **Step 3: 实现会话快照和幂等建单**

在服务层实现两个公开方法：`create_draft_from_conversation(user_id, conversation_id, actor_type, actor_id)` 和 `transition(ticket_id, actor_type, actor_id, target_status, body, metadata)`。它们分别负责生成幂等草稿和执行经过白名单校验的状态转换。

建单前调用 `ConversationStore.get_conversation(conversation_id, user_id)`；从最近消息和已持久化的安全字段提取标题、摘要、设备/故障线索、`safety_level`、`escalation_required` 和升级原因。前端传入的摘要、安全等级和来源字段全部忽略。通过 `UNIQUE(user_id, conversation_id)` 和服务层查询保证重复请求幂等。

- [ ] **Step 4: 实现状态转换和审计事件**

只允许 `ALLOWED_TRANSITIONS` 中的转换；每次成功转换在同一事务内更新工单并插入 `ticket_events`。`resolved_pending_confirm → closed` 只能由用户确认或显式管理员动作触发；`reopened` 必须清除 `closed_at` 和 `user_confirmed_at`。高风险工单不能被 `system` actor 自动关闭。

- [ ] **Step 5: 运行测试确认通过并提交**

运行：`pytest -q backend/tests/unit/test_ticket_service.py backend/tests/unit/test_ticket_store.py`。

```bash
git add backend/app/services/ticket_service.py backend/app/services/ticket_store.py backend/tests/unit/test_ticket_service.py
git commit -m "feat: add ticket lifecycle service"
```

## Task 3: 将会话附件提升为工单证据

**Files:**

- Modify: `backend/app/services/attachment_store.py`
- Modify: `backend/app/services/ticket_service.py`
- Test: `backend/tests/unit/test_ticket_service.py`
- Test: `backend/tests/unit/test_attachments.py`

- [ ] **Step 1: 写失败测试并确认失败**

验证建单时仅关联当前会话、状态为 `ready` 的附件；附件关系写入 `ticket_evidence`；提升后刷新保留时间；`cleanup_expired()` 不删除已绑定工单的 payload；附件提升失败时建单回滚或执行补偿。

运行：`pytest -q backend/tests/unit/test_ticket_service.py backend/tests/unit/test_attachments.py`。

- [ ] **Step 2: 增加原子提升方法**

在 `AttachmentStore` 增加 `promote_to_ticket(conversation_id, attachment_ids, ticket_id, retention_until)` 方法。它验证附件属于会话且未删除，更新案件保留时间，并建立唯一证据关联；清理 SQL 增加 `NOT EXISTS (SELECT 1 FROM ticket_evidence WHERE ticket_evidence.evidence_id = attachments.id)` 条件。

- [ ] **Step 3: 在建单服务中接入提升和补偿**

建单、事件和证据关系使用同一 SQLite 事务；任一步失败时删除新工单和事件并恢复未完成的附件状态，不能留下用户看不到的长期文件。

- [ ] **Step 4: 运行测试确认通过并提交**

运行：`pytest -q backend/tests/unit/test_ticket_service.py backend/tests/unit/test_attachments.py`。

```bash
git add backend/app/services/attachment_store.py backend/app/services/ticket_service.py backend/tests/unit/test_ticket_service.py backend/tests/unit/test_attachments.py
git commit -m "feat: retain ticket evidence attachments"
```

## Task 4: 实现普通用户工单 API

**Files:**

- Create: `backend/app/api/tickets.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/models/ticket.py`
- Test: `backend/tests/integration/test_api_tickets.py`

- [ ] **Step 1: 写失败集成测试**

覆盖匿名 401、从本人会话建草稿、重复建单幂等、列表/详情所有权、用户提交、补充公开消息、确认解决、仍未解决重开、跨用户 404、非法状态 422，以及内部备注不出现在用户响应。

- [ ] **Step 2: 运行测试确认失败**

运行：`pytest -q backend/tests/integration/test_api_tickets.py`。

- [ ] **Step 3: 实现最小用户路由**

提供以下路由，所有路由显式依赖 `get_current_user`：

```text
POST /api/tickets/from-conversation  -> 创建或返回 draft
POST /api/tickets/{id}/submit       -> draft -> submitted
GET  /api/tickets                   -> 当前用户列表
GET  /api/tickets/{id}              -> 当前用户详情和公开事件
POST /api/tickets/{id}/messages     -> 追加公开补充信息
POST /api/tickets/{id}/confirm-resolution -> resolved_pending_confirm -> closed
POST /api/tickets/{id}/reopen      -> resolved_pending_confirm -> reopened
```

后端从会话读取内容，不接受前端伪造摘要、安全等级、来源或其他用户 ID。

- [ ] **Step 4: 挂载路由并运行测试**

在 `main.py` 注册 `tickets.router`，运行：`pytest -q backend/tests/integration/test_api_tickets.py backend/tests/integration/test_api_authorization.py`。

- [ ] **Step 5: 提交独立变更**

```bash
git add backend/app/api/tickets.py backend/app/main.py backend/app/models/ticket.py backend/tests/integration/test_api_tickets.py
git commit -m "feat: expose user ticket workflow API"
```

## Task 5: 实现管理员工单队列和处理 API

**Files:**

- Create: `backend/app/api/admin_tickets.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_api_tickets.py`

- [ ] **Step 1: 写失败测试并确认失败**

验证普通用户访问管理员路径为 403；管理员可按状态、优先级、安全等级和负责人筛选；管理员可接单、转派、写内部备注、发公开回复、请求补充、标记待确认、关闭和重开；每个操作产生事件。

运行：`pytest -q backend/tests/integration/test_api_tickets.py -k admin`。

- [ ] **Step 2: 实现管理员路由**

使用 `require_admin`，提供：

```text
GET   /api/admin/tickets
GET   /api/admin/tickets/{id}
PATCH /api/admin/tickets/{id}
POST  /api/admin/tickets/{id}/events
```

`PATCH` 只接受 `status`、`priority`、`assignee_user_id`、`resolution_summary`；事件接口区分 `public_reply` 和 `internal_note`，内部事件仅管理员详情可见。

- [ ] **Step 3: 运行完整后端集成测试并提交**

运行：`pytest -q backend/tests/integration/test_api_tickets.py backend/tests/integration/test_api_admin.py backend/tests/integration/test_api_authorization.py`。

```bash
git add backend/app/api/admin_tickets.py backend/app/main.py backend/tests/integration/test_api_tickets.py
git commit -m "feat: add admin ticket operations"
```

## Task 6: 增加前端类型、API、store 和用户页面

**Files:**

- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/tickets.ts`
- Create: `frontend/src/stores/tickets.ts`
- Create: `frontend/src/views/TicketsView.vue`
- Create: `frontend/src/views/TicketDetailView.vue`
- Create: `frontend/src/components/TicketDraftCard.vue`
- Create: `frontend/src/components/TicketTimeline.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/AppHeader.vue`
- Modify: `frontend/src/components/AssistantMessage.vue`
- Test: `frontend/src/api/__tests__/tickets.test.ts`
- Test: `frontend/src/stores/__tests__/tickets.test.ts`
- Test: `frontend/src/components/__tests__/TicketDraftCard.test.ts`
- Test: `frontend/src/components/__tests__/TicketTimeline.test.ts`

- [ ] **Step 1: 写失败测试并确认失败**

验证 API 使用 credentials、正确编码 ticket id、解析 401/404；store 能加载列表、打开详情、提交草稿、确认解决和重开；组件不渲染内部备注。

运行：`cd frontend; npm test -- --run src/api/__tests__/tickets.test.ts src/stores/__tests__/tickets.test.ts`。

- [ ] **Step 2: 增加类型和 API 客户端**

在 `types/index.ts` 增加 `TicketStatus`、`TicketPriority`、`Ticket`、`TicketEvent`、`TicketEvidence`；`tickets.ts` 实现 `createDraftFromConversation`、`submitTicket`、`listTickets`、`getTicket`、`addTicketMessage`、`confirmResolution`、`reopenTicket`。

- [ ] **Step 3: 实现 store、页面和建单入口**

store 只保存公开字段；详情页显示状态、摘要、设备信息、公开时间线和证据元数据，提供补充说明/附件和“已解决/仍未解决”；`TicketDraftCard` 先显示服务端草稿，再由用户确认提交。`AssistantMessage.vue` 仅在 `escalation_required === true` 或用户明确触发时显示入口，不能根据前端文本推断安全等级。

- [ ] **Step 4: 增加路由和导航**

注册 `/tickets`、`/tickets/:id`，均要求登录；Header 增加“我的工单”入口；保留现有聊天、图谱和管理员路由行为。

- [ ] **Step 5: 运行测试、构建并提交**

运行：`cd frontend; npm test -- --run src/api/__tests__/tickets.test.ts src/stores/__tests__/tickets.test.ts src/components/__tests__/TicketDraftCard.test.ts src/components/__tests__/TicketTimeline.test.ts`。

```bash
git add frontend/src/types/index.ts frontend/src/api/tickets.ts frontend/src/stores/tickets.ts frontend/src/views/TicketsView.vue frontend/src/views/TicketDetailView.vue frontend/src/components/TicketDraftCard.vue frontend/src/components/TicketTimeline.vue frontend/src/router/index.ts frontend/src/components/AppHeader.vue frontend/src/components/AssistantMessage.vue frontend/src/api/__tests__/tickets.test.ts frontend/src/stores/__tests__/tickets.test.ts frontend/src/components/__tests__/TicketDraftCard.test.ts frontend/src/components/__tests__/TicketTimeline.test.ts
git commit -m "feat: add user ticket experience"
```

## Task 7: 增加管理员前端队列和详情操作

**Files:**

- Create: `frontend/src/api/adminTickets.ts`
- Create: `frontend/src/components/AdminTicketQueue.vue`
- Create: `frontend/src/components/AdminTicketDetail.vue`
- Modify: `frontend/src/views/AdminView.vue`
- Modify: `frontend/src/types/index.ts`
- Test: `frontend/src/components/__tests__/AdminTicketQueue.test.ts`
- Test: `frontend/src/components/__tests__/AdminTicketDetail.test.ts`

- [ ] **Step 1: 写失败组件测试并确认失败**

验证列表按筛选参数请求；详情区分 AI 建议、公开回复和内部备注；非管理员不渲染管理操作；状态按钮根据允许转换禁用。

运行：`cd frontend; npm test -- --run src/components/__tests__/AdminTicketQueue.test.ts src/components/__tests__/AdminTicketDetail.test.ts`。

- [ ] **Step 2: 实现品牌管理员 API、队列和详情**

`adminTickets.ts` 实现列表、详情、更新和事件 API；队列支持 `status`、`priority`、`safety_level`、`assignee_user_id` 查询；详情展示会话摘要、来源、附件元数据和完整事件时间线。`AdminView.vue` 保留既有用户、反馈统计、日志和知识库区块，增加工单区块或标签页。

- [ ] **Step 3: 运行测试和构建并提交**

运行：`cd frontend; npm test -- --run; npm run build`。

```bash
git add frontend/src/api/adminTickets.ts frontend/src/components/AdminTicketQueue.vue frontend/src/components/AdminTicketDetail.vue frontend/src/views/AdminView.vue frontend/src/types/index.ts frontend/src/components/__tests__/AdminTicketQueue.test.ts frontend/src/components/__tests__/AdminTicketDetail.test.ts
git commit -m "feat: add admin ticket workspace"
```

## Task 8: 文档、回归验证和发布前检查

**Files:**

- Modify: `README.md`
- Test: all existing backend and frontend suites

- [ ] **Step 1: 更新 README**

说明第一阶段只服务一个无人机商家/品牌，支持自建工单、品牌管理员处理、用户确认/重开和案件证据留存；外部 CRM、图片识别、视频诊断、设备遥测和多商家 SaaS 仍未实现。

- [ ] **Step 2: 运行后端完整验证**

```powershell
cd backend
$env:PYTHONPATH = ((Get-Location).Path + ';' + (Resolve-Path .venv/Lib/site-packages).Path)
& .\.python-runtime\cpython-3.11.16-windows-x86_64-none\python.exe -m pytest -q
& .\.python-runtime\cpython-3.11.16-windows-x86_64-none\python.exe -m compileall -q app eval
```

预期：现有测试和工单测试全部通过，compileall 退出码为 0。

- [ ] **Step 3: 运行前端完整验证**

```powershell
cd frontend
npm test -- --run
npm run build
```

预期：Vitest 全部通过，生产构建退出码为 0。

- [ ] **Step 4: 检查 diff 和工作区边界**

```powershell
git diff --check
git status --short
git diff --stat HEAD~8..HEAD
```

确认工单提交只包含计划范围内的文件，工作区原有未提交修改没有被重置、清理或覆盖。

- [ ] **Step 5: 提交文档更新**

```bash
git add README.md
git commit -m "docs: document after-sales ticket workflow"
```

## 计划自审

- 设计中的三张工单表、三类角色、状态转换、证据提升、用户确认/重开、管理员处理、审计和权限均有对应任务。
- 草稿到提交的流程通过 `POST /api/tickets/{id}/submit` 明确化，避免用户确认步骤没有后端动作。
- 没有把外部 CRM、图片/视频诊断、设备遥测、多租户或新 RBAC 混入第一阶段。
- 所有数据库写入集中在 Store/Service；API 只负责鉴权、输入校验和响应映射。
- 既有会话、附件、认证、反馈和管理员功能保留，并在最后阶段做回归验证。
