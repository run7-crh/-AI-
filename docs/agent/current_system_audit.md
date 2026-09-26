# 现有系统只读审查报告（阶段 1）

- 审查日期：2026-09-26
- 分支：`codex/auth-admin`（HEAD = `464cb53`）
- Git 状态：工作区仅有 `README.md` 未提交修改（362+/67-，18 节模板重写，待用户定夺 License 与截图），无其他未提交内容
- 审查方式：**纯只读**。本次未修改任何代码、配置、依赖、数据库与 `data/` 知识库；报告中的每一条结论都标注了代码证据（`文件:行号`）
- 测试基线：来自 2026-09-25 收官记录（后端 pytest 409 passed + compileall OK；前端 vitest 99 passed / 25 文件 + build OK）。本次只读审查未重跑测试（pytest 会写入缓存文件），阶段 2 实施前应先复跑该基线作为回归起点

---

## 1. 当前系统真实架构

按真实代码绘制的分层架构（非设计稿）：

```text
浏览器（Vue 3 + TS + Pinia，7 条路由，main.ts → router/index.ts）
   │  REST + SSE（/api/*，Vite dev 代理 → :8000；api/chat.ts 手写 SSE 解析）
   ▼
FastAPI（app/main.py，lifespan 装配）
   │  Cookie 会话鉴权（get_current_user）/ slowapi 限流 / 统一错误处理 / SSE 编排
   │
   ├─ LangGraph Agent 工作流（graph/builder.py，13 节点 + 5 路由函数，固定拓扑）
   │     main.py:208-216：延迟导入 build_graph(_indexer.get_retriever()) → chat_module.set_graph()
   │     检索器经 functools.partial 注入 judge_relevance / rag_retrieve / multi_step_reason 三个节点
   │
   ├─ RAG 管线（app/rag/）
   │     indexer.py（递归读取 data/drone，版本化原子重建）→ Chroma collection「drone_kb」
   │     embedding.py（BAAI/bge-large-zh-v1.5，1024 维，本地）+ retriever.py（向量召回 3 倍候选
   │     + BGEReranker CrossEncoder 重排 + 元数据硬/软过滤 + 文档类型优先级排序）
   │     graph_builder.py（知识图谱 kg.json，仅可视化，不参与检索）
   │
   ├─ 服务层（SQLite WAL，12 张表，全部带 PRAGMA 缺列迁移）
   │     users/sessions（auth_store）· conversations/messages/message_attachments（conversation_store）
   │     attachments（attachment_store）· query_log（query_log_service，27 列）
   │     feedback（feedback_service）· tickets/ticket_events/ticket_evidence（ticket_store）
   │     fault_progress（fault_progress_service）
   │
   └─ 外部服务：DeepSeek（MODEL_FLASH=deepseek-chat / MODEL_PRO_CHAT / MODEL_PRO_REASON=deepseek-reasoner）、
         Tavily（联网兜底，graph/tools.py tavily_search）
```

一次提问的真实数据流（`api/chat.py:162-505`）：

```text
POST /api/chat（限流 10/min，Cookie 鉴权，会话归属校验）
  → 附件 prepare_chat_attachments（可选，临时上下文不落库）
  → 用户消息落库 → 取最近 10 条历史（tiktoken 截断 6000 token）
  → fault_progress.record_confirmation（"确认执行+仍无效"计数）→ has_repeated_failure 阈值检查
  → 组装 input_state（含 prior_troubleshoot_failed）→ graph.astream_events(v2)
  → SSE 事件：stage / token / reasoning / node_end / attachment / final / meta / error / done
  → 收尾：query_log 27 列全量落库（finally + asyncio.shield 保证断连不丢）
        → assistant 消息落库（含 safety/intent/metadata_constraints/escalation_required/sources/judge_log）
```

---

## 2. 当前 Agent 架构（真实 LangGraph 图）

### 2.1 真实拓扑（与 `graph/builder.py` 代码逐边核对）

```text
START
  ↓
rewrite_query（指代消解改写）
  ↓
decompose_question（一次 LLM 结构化输出：意图 / 机型·部件·故障约束 / 安全判断 / 是否多步）
  ├─ is_chitchat 且非高风险且无附件 ──────▶ chitchat_node ─▶ END
  ├─ needs_decomposition 且有有效子问题 ─▶ multi_step_reason ──────────┐
  └─ 否则 ─▶ judge_relevance（轻量检索 top1≥0.5 短路 → 完整检索 avg≥0.4 → LLM 兜底）
               ├─ 相关 ─▶ rag_retrieve ─▶ rag_quality_eval
               │             ├─ 通过（avg>0.7 / 灰区 LLM 通过）─▶ generate_local ──┤
               │             ├─ 不通过且 correction_count<1 ─▶ query_corrector ─▶ rag_retrieve（CRAG 回路，≤1 次）
               │             └─ 不通过且已纠正 ─▶ web_search ─▶ generate_online ──┤
               └─ 不相关 ─▶ web_search ─▶ generate_online ────────────────────────┤
                                                                                  ▼
                                              combined_quality_check（幻觉+质量一次 LLM 判定）
                                                ├─ 通过 ─▶ END
                                                └─ 不通过 ─▶ quality_fail（附警告，不覆盖答案）─▶ END
```

5 个路由函数（`builder.py`）：`route_after_decompose`(:80，高风险覆盖闲聊快速通道 :86-90)、`route_after_relevance`(:60)、`route_after_rag_quality`(:66，CRAG 循环)、`route_after_generate`(:102)、`route_after_combined_quality`(:108)。

### 2.2 节点明细（作用 / 输入 / 输出 / LLM / Tool / 分支）

| # | 节点 | 作用 | 读入 State | 写出 State | LLM 调用 | Tool | 分支 |
|---|------|------|-----------|-----------|---------|------|------|
| 1 | `rewrite_query` (nodes.py:144) | 指代消解改写；输出异常（超长/多行/Markdown）时退回原 query | query, history | rewritten_query | ✅ MODEL_FLASH, temp 0.7 | — | 输出异常→保留原查询 |
| 2 | `decompose_question` (nodes.py:183) | **全图唯一的"理解"节点**：意图分类+多步分解+安全判断+元数据约束，一次结构化输出 | rewritten_query | is_chitchat, needs_decomposition, reasoning_steps, intent, metadata_constraints, document_type_priority, safety_flag/level/situation, user_requests_human | ✅ MODEL_FLASH + `DecomposeSchema`（tools.py:140，11 字段） | — | LLM 失败→`_infer_safety_from_query`+`infer_intent` 关键词兜底 (:199-225)；高风险强制 intent=flight_safety (:273-275) |
| 3 | `chitchat_node` (nodes.py:591) | 闲聊快速通道（仍拼安全/升级指令片段） | query, history, safety_* | final_answer, route_path=chitchat, escalation_required | ✅ MODEL_PRO_CHAT 流式 | — | →END |
| 4 | `judge_relevance` (nodes.py:312) | 相关性三级判断：top1 重排分≥0.5 短路→top3 均分≥0.4 短路→LLM 兜底；时效性关键词跳过一切短路 (:298-308) | rewritten_query, metadata_constraints, document_type_priority | is_relevant, judge_log | 灰区才 ✅（evaluate） | retrieve(top_k=1 / top_k=3) | relevant→rag_retrieve / 否则→web_search |
| 5 | `rag_retrieve` (nodes.py:422) | 知识库检索（元数据过滤+重排在检索器内完成） | rewritten_query, metadata_constraints, document_type_priority | retrieval_result, avg_reranker_score | — | retrieve(top_k=3) | — |
| 6 | `rag_quality_eval` (nodes.py:459) | 检索质量评估：avg>0.7 直接过、<0.3 直接不过、灰区 LLM (:454-455) | retrieval_result, avg_reranker_score | rag_quality_pass, judge_log | 灰区才 ✅ | — | pass→generate_local；fail 未纠正→query_corrector；fail 已纠正→web_search |
| 7 | `query_corrector` (nodes.py:525) | CRAG 纠错：按失败原因改写查询，correction_count+1，回投检索 | rewritten_query, judge_log | rewritten_query, correction_count | ✅ MODEL_FLASH | — | 回到 rag_retrieve（≤1 次，builder.py:74） |
| 8 | `web_search` (nodes.py:581) | Tavily 兜底检索，结果统一为 Evidence 结构 | rewritten_query | web_search_result | — | tavily_search(max_results=5) | — |
| 9 | `generate_local` (nodes.py:617) | 本地证据生成：售后专员人设七段结构提示词（prompts.py:196）；拼接紧急处置/人工升级片段；低置信（均分<0.45 或无有效证据 :65,634-642）计入升级 | rewritten_query, query, history, retrieval_result, safety_*, attachment_context, prior_troubleshoot_failed | final_answer, route_path=local, escalation_required | ✅ MODEL_PRO_CHAT 流式 | — | LLM 失败→兜底文案 |
| 10 | `generate_online` (nodes.py:671) | 联网生成；搜索失败置 quality_warning 且按低置信升级 (:686-696) | rewritten_query, web_search_result, … | final_answer, route_path=online, quality_warning, escalation_required | ✅ MODEL_PRO_CHAT 流式 | — | 同上 |
| 11 | `multi_step_reason` (nodes.py:735) | 最多 5 个子问题去重逐个 RAG；某子问题最高分<0.3 且确为多步时 Tavily 兜底 (:783-806)；证据去重合并 | reasoning_steps, metadata_constraints, … | final_answer, route_path=decomposition, retrieval_result(合并), escalation_required | ✅ MODEL_PRO_REASON 流式（思维链经 reasoning 事件流出） | retrieve + tavily_search | 单子问题检索失败不阻塞 |
| 12 | `combined_quality_check` (nodes.py:884) | 幻觉+质量一次判定；源材料按 route_path 取并 2000 字截断 (:919-921) | final_answer, retrieval_result, web_search_result, attachment_context | has_hallucination, answer_quality_pass, quality_check_error, judge_log | ✅ MODEL_FLASH + `CombinedQualitySchema` | — | pass→END；fail→quality_fail |
| 13 | `quality_fail` (nodes.py:965) | 追加质量警告文本（错误/幻觉/质量未过三选一），不覆盖答案 | has_hallucination, quality_check_error | quality_warning | — | — | →END |

**AgentState 五组字段**（`graph/state.py:15-69`）：输入（query/conversation_id/history/attachment_*）、路由中间产物（rewritten_query/intent/metadata_constraints/document_type_priority/is_relevant/…）、质量（has_hallucination/answer_quality_pass）、安全（safety_flag/safety_level/safety_situation/user_requests_human/prior_troubleshoot_failed/escalation_required）、输出（final_answer/route_path/quality_warning）+ `judge_log`（`operator.add` 追加）。

### 2.3 现有"Tool 层"的真实形态

没有 ReAct 式模型自主选工具。外部能力以**固定拓扑注入**方式接入（`graph/tools.py`）：`call_llm`(:173，tenacity 3 次重试，流式不重试)、`evaluate`(:283，LLM 判官)、`retrieve`(:309，包装 RAGRetriever)、`tavily_search`(:351)。不存在 `search_sop` / `get_device` / `get_ticket` / `create_ticket` 等业务 Tool——图对工单、用户、设备零访问能力。

---

## 3. 工单系统现状

### 3.1 数据层

三张工单表 + 两张关联表（均已核实建表代码）：

| 表 | 关键字段 | 说明 |
|---|---|---|
| `tickets` | id, ticket_number, user_id, conversation_id, title, problem_summary, device_model, serial_number, firmware_version, fault_category, priority, safety_level, escalation_reason, assignee_user_id, status, resolution_summary, created_at/updated_at/resolved_at/closed_at/user_confirmed_at | `UNIQUE(user_id, conversation_id)` 保证一会话一工单；serial_number/firmware_version **字段存在但全链路无人写入**（models/ticket.py:34-35） |
| `ticket_events` | actor_type(user/admin/agent/system), event_type, from_status, to_status, body, metadata | 只追加审计流水 |
| `ticket_evidence` | ticket_id, evidence_type(attachment/message/query_log), evidence_id | 唯一约束；附件提升后保留期延至 30 天（ticket_service.py:53,207-212） |

### 3.2 状态机与服务层（`services/ticket_service.py`）

- `ALLOWED_TRANSITIONS`(:20-30)：`draft → submitted → assigned → in_progress → (waiting_user) → resolved_pending_confirm → closed / reopened`，cancelled 与 closed 为终态。唯一事实源，API 层无法绕过；并发用 `WHERE status=?` 乐观锁守卫（ticket_store.apply_transition）。
- `USER_TRANSITIONS`(:35)：普通用户仅能 submitted/closed/reopened/cancelled。
- **`agent`/`system` 角色被显式禁止做任何状态转换**（:465-466）；高风险（safety_level=high）工单禁止 agent/system 关闭（:460-464）。
- 快照派生 `_build_snapshot`(:252-306)：**服务端数据是唯一事实源**，客户端声称的摘要/安全等级一律忽略。从 messages（优先）+ query_log（补缺）提取：title（最后一条用户问题）、problem_summary（用户问题 + AI 初步建议 240 字摘要，先剥 Markdown）、device_model/fault_category（来自 metadata_constraints.product_model / fault_type|component）、safety_level/situation、escalation_required、escalation_reason（高风险→"会话中出现高风险安全情形（设备状态：…）"；否则排查未解决→"Agent 已建议联系人工…"）。
- 建单幂等：同 (user, conversation) 重复调用返回同一张草稿，并发竞态以 UNIQUE 兜底 (:129-165)；附件提升失败时删除刚建的草稿补偿回滚 (:181-186)。
- 草稿编辑 `update_draft`(:310-347)：仅属主、仅 draft 状态、仅 title/problem_summary，安全派生字段永不接受客户端覆盖。
- 管理端 `admin_update`(:398-436)：四字段白名单 status/priority/assignee_user_id/resolution_summary。

### 3.3 API 层

用户侧 8 路由（`api/tickets.py`）：`POST /from-conversation`(:74 幂等建草稿)、`GET ""`(:94 我的工单)、`PATCH /{id}/draft`(:102 编辑草稿)、`GET /{id}`(:123 详情，**过滤 internal_note** :28,133)、`POST /{id}/submit`(:143)、`/{id}/messages`(:162 补充信息)、`/{id}/confirm-resolution`(:182 确认关闭)、`/{id}/reopen`(:201)。全部经 `_require_owned_ticket` 做属主校验，跨用户统一 404。

管理端 4 路由（`api/admin_tickets.py`）：`GET ""`(:47 队列，支持 status/priority/safety_level/assignee 筛选)、`GET /{id}`(:67 全量详情含内部备注)、`PATCH /{id}`(:85)、`POST /{id}/events`(:106 public_reply / internal_note)。

### 3.4 前端

- 客户端：两个建单入口——升级触发（`AssistantMessage.vue:153-191`，escalation_required 时安全块/琥珀块内"生成售后工单"按钮）+ 常驻入口（`ConversationTicketPanel.vue:19-26`，ChatPanel.vue:100 挂载）；`TicketDraftModal`+`TicketDraftCard` 弹窗（仅可编辑标题/描述，:100-102 明示"机型、故障分类和安全等级由系统判定，不可编辑"）；`TicketsView`/`TicketDetailView`/`TicketTimeline`（internal_note 前端再防御过滤）。
- 管理端：`AdminTicketQueue`（四维筛选+高风险红徽章）、`AdminTicketDetail`（状态白名单按钮、转派下拉选人、处理结论、公开回复/内部备注、按 actor 分色时间线，其中 agent 事件蓝紫色、`agent_suggestion` 事件文案映射为"AI 建议"）。
- **闭环结论：客户端创建草稿→编辑→提交→管理端接单/转派/要求补充/公开回复/内部备注→待确认→用户确认关闭或重开，全链路真实可用，且被 409+99 个测试中的工单专项测试覆盖。**

---

## 4. Agent 与工单系统当前如何连接（关键结论）

当前连接是**单向、图外、快照式**的，共三条真实通路：

```text
通路 1（图内状态 → 持久化）  chat.py:379-395,509-611
  LangGraph 图跑完后，把 safety_flag/safety_level/safety_situation/escalation_required/
  intent/metadata_constraints/document_type_priority 写入 assistant 消息与 query_log（27 列）；
  另由 _derive_fault_key(chat.py:110-127) 从 troubleshooting/case 证据派生
  fault_key（机型__故障类型）写入 query_log。

通路 2（持久化 → 工单快照）  ticket_service.py:_build_snapshot
  用户点"生成工单草稿"时，TicketService 从上述已落库字段派生快照建单。
  ——注意：派生发生在建单 API 内，不在图内；图本身不知道工单的存在。

通路 3（排查失败计数 → 升级）  fault_progress_service.py
  用户消息同时命中"确认执行"与"仍无效"词表(:47-57)时，对最近 fault_key 累加；
  同会话同故障 ≥2 次（:33）→ 下一轮 input_state 注入 prior_troubleshoot_failed=true
  （chat.py:203-217）→ _compute_escalation_required 命中 → HUMAN_ESCALATION_DIRECTIVE
  + escalation_required=true → 前端出现建单入口。
```

**同样重要的事实（反面）**：

1. **图（Agent）从不调用 TicketService / 工单 API / 任何工单读取**。`create_draft_from_conversation` 的 `actor_type="agent"` 分支（ticket_service.py:121）从未被任何调用方使用；transition 层显式禁止 agent/system 改状态（:465-466）。"Agent 决定建单"不存在——建单永远由用户在前端点击触发。
2. **`agent_suggestion` 事件后端从不写入**。全仓 grep 确认唯一出现处是前端 `AdminTicketDetail.vue:61` 的文案映射——这是为未来预留的死映射，管理端时间线里的"AI 建议"条目目前**不可能出现**。
3. **工单 → Agent 方向完全不存在**：没有任何接口把工单上下文喂给图或检索器，管理端没有任何 AI 分析端点（`adminTickets.ts` 全文仅 list/detail/patch/events 四个函数）。

---

## 5. 功能实现状态总表

| 分类 | 内容 |
|---|---|
| **完整实现** | LangGraph 13 节点固定拓扑 + CRAG 回路；意图路由（10 类）+ 元数据感知检索（机型硬过滤/部件故障软过滤/文档类型优先级/跨机型污染防护）；bge embedding + CrossEncoder 重排 + 三级分数短路；安全分级（high/none × 四态）+ 关键词保守兜底 + 紧急处置指令；人工升级四触发（用户要求/排查失败≥2/高风险/低置信<0.45）；SSE 全协议（stage/token/reasoning/node_end/final/meta/error/done + 停止生成/防串流/断连保日志）；多步分解推理（deepseek-reasoner）；附件上传解析与临时上下文边界；认证与 admin 鉴权；工单全生命周期（状态机+幂等草稿+快照派生+证据提升+草稿编辑+审计事件）；管理台（用户/反馈/日志/知识库导入/索引重建）；知识图谱可视化；query_log 27 列全量落库；离线评估框架与 34 题数据集 |
| **部分实现** | 产品型号识别（仅 4 机型别名表 intent.py:32-44 + 结构化输出保守确认，无 SN/设备档案）；故障分类（FAULT_TERMS 仅 6 条映射 intent.py:54-59 + LLM 结构化 fault_type，无完整故障分类学）；诊断结构化（提示词层面有七段结构【问题判断/安全提醒/建议排查/可能原因/需要补充的信息/来源依据/是否建议转人工】prompts.py:196，但**纯文本输出，无机器可读的 Diagnosis/Evidence/Confidence 结构**）；工单决策（只有 escalation_required 布尔"建议转人工"，无 answer/followup/create_ticket/escalate 的决策节点）；评估指标（有 product_model_accuracy/safety_recall/escalation_accuracy/cross_model_contamination_count，缺故障分类/诊断/工单动作类指标） |
| **接口/类型存在但未接入** | 工单快照建单的 `actor_type="agent"` 分支；`tickets.serial_number`/`firmware_version` 字段（无设备档案，无人写入）；前端 `agent_suggestion`→"AI 建议"文案映射；评估集 `from_query_log` 真实问题回流（README 自述为 0）；token_usage_json（预留 P2，`_infer_models_used` 如实标注"非真实采集" chat.py:145） |
| **前端存在但后端未完成** | 管理端"AI 建议"事件展示（后端无任何写入方，属死代码） |
| **Mock（冒充真实）** | 未发现。联网失败返回错误占位证据并置 quality_warning（如实降级，非伪装）；评估 gold 全部 `gold_status=inferred`（如实标注未复核） |
| **TODO** | 代码中无遗留 TODO/FIXME 标注（grep 核实，仅两处误命中：提示词格式示例与 wikilink 正则） |
| **不存在** | 信息充分性判断与主动追问（ask_followup）；Agent 决策节点（decide_action）；结构化诊断输出对象；工单创建前 Agent 自主建单；管理端 AI Copilot 全部能力（AI 分析面板/诊断/证据/SOP 推荐/处理建议/AI 回复草稿/采用建议/重新分析）；服务记录（service_record）概念；设备/序列号档案；search_sop/search_troubleshooting/get_ticket/get_device 等业务 Tool |

---

## 6. 目标能力逐项对照（任务书第六~十二节 → 现状判定）

| 目标能力 | 判定 | 现状与证据 |
|---|---|---|
| 问题理解 / 结构化 | 🟡 部分实现 | `decompose_question` 一次 LLM 产出 intent/metadata_constraints/安全字段，但只对"当轮 query"，无跨轮信息缺口模型 |
| 信息充分性判断 → 主动追问 | 🔴 缺失 | 无任何追问节点/机制。提示词里有【需要补充的信息】小节与"先确认机型"纪律（prompts.py），但只是回答文本的一部分，不会拦截流程、不会以追问终止本轮、也没有把"缺什么"结构化存下来 |
| 产品型号识别 + 防知识污染 | 🟡 部分实现 | MODEL_ALIASES 4 机型 + 检索器机型硬过滤（retriever.py:103-105）+ 无命中回退通用文档 (:204-206) + `cross_model_contamination_count` 指标；但识别仅靠文本别名匹配，SN/设备档案不存在 |
| 故障分类 | 🟡 部分实现 | fault_type/component 进 constraints 并派生为工单 fault_category；词表仅 6 条，无面向售后的完整故障分类学（任务书第八.3 的清单需结合知识库重定） |
| 智能检索链路（Rewrite→Filter→Recall→Rerank→评估） | 🟢 基本已实现 | rewrite_query（含 CRAG 二次纠正）→ metadata_constraints 过滤 → 向量 3 倍召回 → CrossEncoder 重排 → rag_quality_eval 三级判定 → web 兜底。任务书第九的形态与现状高度吻合，**不应重复建设**，只需把"结构化后的问题"更好地喂给约束抽取 |
| 证据评估 | 🟡 部分实现 | 分数短路 + LLM 灰区判定 + Evidence 17 字段（含 data_type factual/synthetic 透出与前端"模拟案例"标注 SourceCard.vue:43-48,109）；但无"证据是否足够/是否存在冲突证据"的显式评估产物 |
| 结构化诊断（Diagnosis/Evidence/Action/Safety/Confidence/Citation） | 🔴 缺失 | 诊断信息以七段结构**自由文本**存在于回答里；state 与 API 均无结构化诊断对象，管理端更拿不到 |
| 工单决策（answer/followup/create_ticket/escalate 四分支） | 🔴 缺失 | 只有 escalation_required 布尔 + 前端建单按钮。无 decide_action 节点，无"Agent 判定需要售后介入→调用现有建单能力"的通路（且状态机层面 agent 本就被禁止转状态，若要 Agent 建单需走 draft 创建而非 transition，这是设计空间而非缺陷） |
| 管理端 AI Copilot（第十二节全部区块） | 🔴 缺失 | 管理工单台是纯手工 CRUD；唯一 AI 痕迹是死的 `agent_suggestion` 文案映射 |
| AI 辅助而非替代（第十三节安全原则） | 🟢 已具备地基 | 高风险禁系统关闭（ticket_service.py:460-464）、agent/system 禁转状态、synthetic 不得作确诊依据（提示词+前端标注）、"建议联系人工"表述纪律——这些纪律已在现有代码中生效，Copilot 设计应沿用 |
| 服务记录 | 🔴 缺失 | 无 service_record 表/概念；closed 工单只有 resolution_summary 与审计事件可作准服务记录 |

---

## 7. 管理端目前缺少哪些 AI 能力

现有（全部是被动展示，零请求）：时间线 `agent_suggestion` 死文案映射（AdminTicketDetail.vue:61）；工单上的服务端派生快照字段可读（device_model/fault_category/safety_level/escalation_reason，AdminTicketDetail.vue:158-167）。

完全缺失：AI 分析触发按钮与接口；问题摘要/产品识别/故障分类/相关知识/相关 SOP/证据列表/AI 诊断/处理建议/安全提示/AI 回复草稿任何一个区块；"采用建议""重新分析""人工处理"按钮；把 AI 建议写回工单（public_reply 草稿、internal_note、`agent_suggestion` 事件）的写入方；管理端对知识库检索器的任何复用。即任务书第十二节的整个面板从 UI 到 API 到生成逻辑都是空白。

---

## 8. 哪些地方不需要修改（保护清单）

以下能力经审查确认真实可用且与本次升级目标正交，**增量改造必须复用、不得重写**：

1. RAG 全链路：indexer/readers/embedding/retriever/reranker/版本化索引重建（含机型硬过滤与回退策略——这正是任务书要求的"避免知识污染"机制）。
2. LangGraph 现有 13 节点拓扑与 5 路由：升级应在其上**增节点/增状态字段/改路由函数**，不是重写。
3. SSE 协议与 chat.py 的事件编排、停止生成、断连保日志、`meta` 事件字段（新增字段向后兼容的先例已经存在：阶段 2/3 都是往 meta 里加可选字段）。
4. 工单状态机（ALLOWED_TRANSITIONS 是唯一事实源）、幂等建单、快照派生、证据提升、草稿编辑、用户/管理两套 API 与页面。
5. 认证/鉴权、附件系统（含安全校验）、故障进度计数、反馈、知识库导入、限流、错误映射。
6. `data/drone` 知识库与其 frontmatter 身份字段体系（factual/synthetic 隔离已从 metadata 一路贯通到前端标注）。
7. 409+99 测试基线与评估框架骨架（run_eval 的指标注册表结构可直接扩新指标）。

---

## 9. 哪些地方需要增量开发

按任务书阶段划分建议（全部为增量，不推翻现有结构）：

**阶段 3（State/Graph 增量）**
- AgentState 增加结构化产物字段：如 `issue_profile`（机型/部件/故障/现象的结构化汇总）、`information_gaps`（缺失信息清单）、`diagnosis`（结构化诊断对象）、`recommended_action`（answer/followup/create_ticket/escalate 四值决策）。
- `decompose_question` 扩展为真正的 `understand_issue + check_information`：结构化输出增加 information_sufficient / missing_fields；不足时路由到新增 `ask_followup` 节点（生成针对性追问并结束本轮，把缺口写入 state 供下一轮合并）。机型识别可复用 MODEL_ALIASES 并接受 LLM 结构化候选（现有"文本确认才生效"的保守规则建议保留为硬约束、LLM 候选作软提示）。
- 生成节点之后增加 `decide_action`（可用现有 escalation/safety/置信度信号 + 新结构化字段，规则为主、LLM 为辅），决定 answer / followup / create_ticket / escalate；其中 create_ticket 分支**调用现有 `TicketService.create_draft_from_conversation`**（actor_type="agent" 分支已预留），不经第二套工单系统。
- 诊断结构化：把提示词中已有的七段结构升级为（或并行产出）机器可读 JSON（Diagnosis/Evidence ids/Recommended Action/Safety Warning/Confidence/Citations），复用 `with_structured_output` 先例。

**阶段 4（RAG/Tool 接入）**
- 检索侧基本不动；可为管理端 Copilot 增加"按工单上下文检索"的入口（把 problem_summary/device_model/fault_category 拼为检索 query + constraints，直接复用 RAGRetriever）。
- Tool 层按需新增且以业务 Service 包装为准：`get_ticket_context`（管理端分析读取工单+事件+证据）、可选 `search_sop/search_troubleshooting`（即带 document_type 固定约束的 retrieve 变体）。**不建议**做 ReAct 自主选工具，与 README 定位声明保持一致。

**阶段 5（工单前决策落地）**
- decide_action → create_ticket：Agent 在信息充分、需售后介入时自动建草稿（幂等保护已有）；escalate 分支对应现有 HUMAN_ESCALATION_DIRECTIVE 与高风险路径。
- 新增审计：真实写入 `agent_suggestion` 类事件（前端映射已就位），让"Agent 做过什么"进入工单审计流水。

**阶段 6（管理端 AI Copilot）**
- 后端：新增 admin 范围的工单分析端点（如 `POST /api/admin/tickets/{id}/ai-analysis`），输入=工单快照+审计事件+证据附件文本，执行"检索（复用检索器）→ 结构化诊断 → 处理建议 → 回复草稿"，结果可缓存于工单事件（agent_suggestion）或独立存储。
- 前端：在 `AdminTicketDetail.vue` 现有结构内增加 AI 分析面板（摘要/识别/证据/SOP/建议/回复草稿），"采用建议"= 把草稿填入公开回复框（仍由人工点发送），"重新分析"= 重调端点。**不新建管理系统页面**。
- 安全红线沿用第十三节：高风险（safety_level=high 或诊断命中安全词表）时建议区降级为保守提示 + 必须人工处理，AI 不给维修操作类建议。

**阶段 7（评估扩展）**
- run_eval 增加指标：fault_classification_accuracy（对 constraints.fault_type）、diagnosis_quality（结构化字段命中率/引用正确性）、ticket_action_accuracy（四值决策对 gold）、followup_appropriateness（信息不足题是否追问而非硬答）。数据集需按任务书第十八节补场景：信息不足、跨型号、知识冲突、已有工单追问等（现有 34 题无此类）。

**顺手小修（记录在案，非主线）**：main.py:227 FastAPI title 仍是"学AI必备助手 API"；manifest.json document_count=70 vs 实际 71（已有授权记录在案）；`has_source` 检测只认 `[来源：`/`【来源：`（chat.py:549），结构化引用改造时需同步。

---

## 10. 推荐的实际开发顺序

```text
1. 阶段 2：产出《Agent 改造方案》六要素（当前实现分析/目标/影响文件/数据流/风险/验收标准）
   —— 等待用户授权后再动代码（工作区硬性规则）
2. 阶段 3：AgentState + decompose 扩展（信息充分性/缺口） + ask_followup 节点 + 路由函数调整
   回归：现有 409 测试全绿 + 新增节点单测
3. 阶段 4：诊断结构化 + decide_action 节点（answer/followup/escalate 先落地，create_ticket 最后接）
4. 阶段 5：create_ticket 分支接 TicketService（actor_type="agent"）+ agent_suggestion 事件真实写入
   回归：手工验证"客户端创建→管理端处理→解决"闭环不被破坏（任务书第二十节红线）
5. 阶段 6：管理端 Copilot（后端分析端点 → AdminTicketDetail 面板 → 采用/重分析）
6. 阶段 7：评估指标与数据集扩展（含 gold 复核机制）
7. 阶段 8-10：全量回归（后端 pytest + 前端 vitest + build）→ 代码审查 → README 增补 Agent 章节
```

顺序依据：信息充分性与追问是任务书第八节的第一优先能力，也是当前最大的行为缺口；decide_action 是把"聊天机器人"变成"业务 Agent"的分水岭；管理端 Copilot 依赖诊断结构化的产物，放在其后可复用同一套结构；评估扩展放最后可以同时校准前面所有新增行为。

---

## 11. 审查中发现的事实与风险备忘

1. **README.md 有未提交修改**（18 节模板重写 +362/-67），内容与本次代码核查基本一致（13 节点拓扑、阈值常量、API 全表均对得上）；其中两处待用户定夺：License 未定、Demo 截图占位。本次审查未触碰该文件。
2. `agent_suggestion` 是当前系统中"管理端 AI"的全部存量——且是死代码。这决定了阶段 5/6 的工作量是"从零建"，但前端展示映射和 agent 角色权限设计已经留好了插槽。
3. 图对业务的感知边界：Agent 目前只知道"这一轮的问题"，不知道"这个用户是谁、买过什么、这台设备发生过什么"。设备档案（serial_number/firmware_version 字段已预留）是产品识别从"文本猜测"升级为"事实确认"的前提，但建档案属于新业务面，建议列为独立决策点而非塞进本次 Agent 改造。
4. synthetic 隔离现状良好：`data_type` 进向量 metadata（retriever.py:197）→ 证据透出（chat.py meta）→ 前端琥珀标注（SourceCard.vue:109）→ 提示词纪律（"模拟案例不得作为确诊依据" prompts.py 共同纪律 3）。知识库本身未做任何修改。
5. 评估现状的诚实边界：34 题 gold 全部 `inferred` 未人工复核；eval/reports 里只有旧 v1.1（99 题 RAG 主题）的历史数字，**无人机版本从未真实跑过**（无 API key 时指标为 null）。阶段 7 扩展指标时应一并解决"跑一次真实基线"。
6. 测试基线 409+99 为 2026-09-25 记录；本次只读未重跑。任何阶段 3+ 的实施前都应先复跑确认起点干净。
