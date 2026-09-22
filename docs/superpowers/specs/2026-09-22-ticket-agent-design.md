# 售后 Agent 工单闭环设计

日期：2026-09-22

## 目标

在现有无人机售后 Agent 的会话、附件、安全升级、反馈和管理员基础上增加工单闭环，使用户能够从一次未解决的对话创建售后工单，后台管理员能够接单和处理，用户能够确认解决或重新打开。

第一阶段采用自建工单模块，继续使用现有 FastAPI、SQLite、Vue 和服务端 Cookie 会话。现有 `admin` 角色暂时兼任售后处理人员，不新增 `operator` 角色。

## 产品边界

Agent 是后台人员的副驾驶，不是最终工单负责人。Agent 可以提取信息、建议优先级、生成排查步骤和推动流程；后台管理员负责接单、处理和确认解决结果；用户负责补充材料以及最终确认是否解决。

Agent 不得在没有用户确认或明确自动规则的情况下关闭工单，也不得擅自修改负责人、删除证据或把一次回答成功当作故障已经解决。

## 角色与权限

### 普通用户

- 从本人拥有的会话创建工单。
- 查看本人创建的工单及状态时间线。
- 补充说明、附件和联系方式。
- 确认已解决，或选择仍未解决并重新打开。
- 不能读取其他用户的工单、内部备注或后台日志。

### 管理员/售后处理人员

- 查看和筛选全部工单。
- 接单、转派、调整优先级和补充内部备注。
- 查看关联会话、引用来源、安全判断、排查进度和工单证据。
- 回复用户、填写处理结果并将工单置为待用户确认。
- 在用户确认或符合明确自动关闭规则后关闭工单。

### Agent

- 从会话生成工单草稿。
- 提取问题摘要、设备信息、故障类别、排查步骤和升级原因。
- 关联会话中的 query log、消息和附件。
- 建议优先级、安全等级、下一步动作和是否需要人工升级。
- 根据用户补充内容更新 AI 摘要。
- 所有 AI 产出在后台显示为建议，不能绕过后端权限写入不可逆结果。

## 工单生命周期

```text
draft
  → submitted
  → assigned
  → in_progress
  → waiting_user
  → resolved_pending_confirm
  → closed
```

补充状态：

- `reopened`：用户选择仍未解决后重新进入处理流程。
- `cancelled`：重复、误建或用户主动取消的工单。

状态语义：

- `draft`：系统从对话生成，尚未提交。
- `submitted`：用户确认提交，等待后台接单。
- `assigned`：已有处理人员，但尚未开始处理。
- `in_progress`：后台正在排查或维修。
- `waiting_user`：缺少用户信息、附件或现场操作结果。
- `resolved_pending_confirm`：后台认为问题已处理，等待用户确认。
- `closed`：用户确认已解决，或符合已配置的低风险自动关闭规则。

状态变更必须经过后端校验，并写入不可变的事件记录。高风险安全工单不得仅因超时自动关闭。

## 数据模型

### `tickets`

保存工单当前状态和可检索字段：

```text
id
ticket_number
user_id
conversation_id
title
problem_summary
device_model
serial_number
firmware_version
fault_category
priority
safety_level
escalation_reason
assignee_user_id
status
resolution_summary
created_at
updated_at
resolved_at
closed_at
user_confirmed_at
```

`user_id` 和 `conversation_id` 是必需的。工单创建时，后端从会话、消息和 query log 读取结构化字段，不信任前端直接提交的摘要或安全等级。

### `ticket_events`

保存状态和操作审计：

```text
id
ticket_id
actor_type       # user / admin / agent / system
actor_id
event_type
from_status
to_status
body
metadata_json
created_at
```

事件记录只追加，不允许通过普通 API 修改历史事件。

### `ticket_evidence`

保存工单与证据的关联：

```text
id
ticket_id
evidence_type    # attachment / message / query_log
evidence_id
created_at
```

现有附件是会话级临时文件。建单时必须把关联附件提升为工单证据，延长保留期限；没有成功建立工单证据关系时，不得把附件当作长期案件材料。

## 用户流程

1. 用户正常使用聊天和引导式排查。
2. 用户点击“创建售后工单”，或 Agent 在高风险、连续排查失败等条件下展示升级建议。
3. 前端请求后端生成工单草稿。
4. 后端根据会话内容生成摘要并关联消息、query log 和附件。
5. 用户确认摘要、补充缺失信息后提交。
6. 后台管理员在工单队列中接单并处理。
7. 管理员填写处理结果，将状态变为 `resolved_pending_confirm`。
8. 用户选择“已解决”后关闭，选择“仍未解决”后重新打开。

系统不应为每一次普通问答自动创建工单，除非命中高风险或明确的升级策略。

## 后台流程

管理员页面包含：

- 工单列表：按状态、优先级、安全等级、负责人和时间筛选。
- 工单详情：用户问题、Agent 摘要、完整会话、引用来源、排查进度、附件和事件时间线。
- 操作区：接单、转派、请求补充信息、添加内部备注、回复用户、标记待确认、关闭或重新打开。

公开回复与内部备注必须在数据模型和前端展示上分开，内部备注不得返回普通用户 API。

## API

### 用户接口

```text
POST  /api/tickets/from-conversation
GET   /api/tickets
GET   /api/tickets/{ticket_id}
POST  /api/tickets/{ticket_id}/messages
POST  /api/tickets/{ticket_id}/confirm-resolution
POST  /api/tickets/{ticket_id}/reopen
```

### 管理接口

```text
GET   /api/admin/tickets
GET   /api/admin/tickets/{ticket_id}
PATCH /api/admin/tickets/{ticket_id}
POST  /api/admin/tickets/{ticket_id}/events
```

用户接口按 `user_id` 做所有权过滤；管理员接口使用现有 `require_admin`。资源不属于当前用户时统一返回 404，避免泄露资源是否存在。

`POST /api/tickets/from-conversation` 必须在后端验证会话属于当前用户，并从服务端持久化数据构建工单内容。重复请求需要幂等，避免同一会话产生重复工单。

## 前端范围

### 用户侧

- 助手消息中的“创建工单”按钮。
- 建单确认卡片，展示问题摘要、设备信息、排查记录和证据。
- “我的工单”列表。
- 工单详情和状态时间线。
- 补充信息和附件。
- “已解决”和“仍未解决”操作。

### 管理员侧

- 工单队列和筛选。
- 工单详情和事件时间线。
- AI 摘要与建议的人工确认入口。
- 接单、转派、公开回复、内部备注和状态操作。

第一阶段不增加新的 UI 框架，不重做现有聊天页和管理员页布局。

## 安全、隐私与一致性

- 业务权限由后端强制执行，前端隐藏按钮不作为授权手段。
- 工单证据继承会话和附件的用户归属；管理员读取证据必须走明确管理 API。
- 不在普通响应中返回附件正文、存储路径、密码哈希或 session token。
- 高风险安全场景保留现有安全提示和人工升级语义；工单状态不能覆盖安全处置建议。
- 工单创建、状态变化、分派、回复、关闭和重开均写入事件审计。
- 建单、状态更新和证据提升使用事务或等价的补偿逻辑，不能产生“工单已创建但证据关系丢失”的半完成状态。

## 测试与验收

后端：

- 工单建表和旧数据库迁移可重复执行。
- 普通用户只能创建和读取自己的工单。
- 管理员能够列出、接单、转派和更新全部工单。
- 非法状态跳转被拒绝。
- 重复建单请求幂等。
- 建单时消息、query log 和附件证据正确关联。
- 附件提升失败时不会产生不可追踪的长期文件。
- 用户确认后关闭，用户选择未解决后重开。
- 高风险工单不能被普通自动关闭规则关闭。
- 所有关键操作产生事件审计。

前端：

- 建单确认、工单列表、详情和确认解决流程。
- 管理员队列、详情和状态操作。
- 401、403、404 和非法状态错误提示。
- 现有聊天、SSE、附件、反馈、认证和管理员回归测试继续通过。

## 非目标

- 第一阶段不接入 Zendesk、ServiceNow 或其他外部 CRM。
- 不实现 OAuth、短信、邮箱、多租户或细粒度 RBAC。
- 不实现图片识别、视频诊断或设备遥测接入；工单模型只预留证据类型和扩展字段。
- 不让 Agent 代替人工直接关闭高风险或争议工单。
