# Agent 增量改造目标架构（阶段 2 设计稿）

- 日期：2026-09-26
- 性质：**纯设计文档，未修改任何代码/数据库/知识库/前端/配置**
- 事实基础：[current_system_audit.md](current_system_audit.md)（阶段 1 只读审查，所有"现状"结论均带代码证据）
- 本文遵守工作区硬性规则：逐阶段授权、一套工单系统、答案只依据 data/drone、安全优先、禁止 Mock

---

## 1. 当前架构总结（改造的出发点）

当前系统 = **固定拓扑 Agentic Workflow + Corrective RAG + 完整工单闭环**，三条已验证的事实决定了改造形态：

1. **图是 13 节点 + 5 路由的固定拓扑**（`graph/builder.py`），检索与质量内核（rewrite/judge/rag_retrieve/quality_eval/corrector/web_search/quality_check）成熟且有测试覆盖——这些**不动**。
2. `decompose_question` 已经承担了"理解问题"的 80%：意图、机型/部件/故障约束、安全分级、闲聊/多步判定，一次结构化 LLM 调用产出（`nodes.py:183`，`DecomposeSchema` 11 字段 `tools.py:140`）。缺的只是**信息充分性判断与缺口结构**。
3. Agent 与工单仅"单向、图外、快照式"连接：图状态落库（messages + query_log 27 列）→ 建单时 `_build_snapshot` 反向派生。`create_draft_from_conversation` 已接受 `actor_type="agent"`（`ticket_service.py:121`）但从未被调用；管理端 `agent_suggestion` 事件文案映射已就位（`AdminTicketDetail.vue:61`）但后端从不写入——**两个插槽都已预留，只差接线**。

对任务书第三节 8 个问题的直接回答：

| 问题 | 结论 |
|---|---|
| 哪些 State 可直接复用 | `query/history/metadata_constraints/document_type_priority/safety_flag/safety_level/safety_situation/user_requests_human/prior_troubleshoot_failed/escalation_required/retrieval_result/avg_reranker_score/route_path/judge_log` 全部复用，语义不变 |
| 哪些 State 需要增加字段 | 7 个（见第 3 节）：issue_profile、information_sufficient、information_gaps、followup_just_asked、diagnosis、recommended_action、auto_create_ticket |
| 哪些 Node 可扩展 | `decompose_question`（追加充分性输出，不改名不挪位）、`generate_local`（消费 diagnosis）、`route_after_decompose`（追问分支） |
| 哪些 Node 不应修改 | `rewrite_query / judge_relevance / rag_retrieve / rag_quality_eval / query_corrector / web_search / generate_online / multi_step_reason / chitchat_node / quality_fail` 逻辑零改动；`combined_quality_check` 仅改出边（后面插 decide_action） |
| 新 Node 放哪里 | `ask_followup`（decompose 分支 → END）、`diagnose`（local 支路 rag_quality_eval 与 generate_local 之间）、`decide_action`（combined_quality_check 之后） |
| 哪些能力通过 Service 实现 | 管理端 AI 分析编排（新 `ticket_analysis_service.py`）；Agent 建单（**复用 TicketService**，chat.py 在图运行后调用）；诊断 schema 定义放 `graph/tools.py`（与 DecomposeSchema 同层） |
| 哪些能力通过 Tool 暴露 | **不新增 graph tool**。`retrieve` 已参数化（constraints + priority），`call_llm/evaluate/tavily_search` 复用；管理端服务直接复用 `call_llm` + `RAGRetriever`。不做 ReAct 自主选工具（与 README 定位声明一致） |
| 哪些能力不交给 LLM | ①工单状态转换（白名单已硬编码）；②recommended_action 终值（LLM 只供给信号，规则出终值）；③safety_level 终值（清洗+关键词兜底，沿用）；④synthetic 能否作确诊依据（永远不可）；⑤citations 真实性（程序校验 ⊆ evidence ids）；⑥关闭/取消工单（agent 永远无权） |

---

## 2. 改造目标

把当前"回答 → 用户点按钮 → 建单"升级为"**理解 → 判断 → 检索 → 诊断 → 决策 → 业务动作**"，同时保持第 17 节全部红线。增量式改造公式：

```text
现有系统（零重写）
 + 信息充分性判断与主动追问（decompose 扩展 + ask_followup 节点）
 + 结构化诊断（diagnose 节点 + DiagnosisSchema）
 + 业务决策（decide_action 确定性规则节点）
 + Agent 建单（chat.py 调用现有 TicketService，actor_type="agent"）
 + 管理端 AI Copilot（新分析 Service + 1 个端点 + AdminTicketDetail 内嵌面板）
```

**明确不做**：新 Ticket 系统 / AgentTicketService / 工单新表 / ReAct 自主工具选择 / 重写 13 节点 / 改 RAG 内核 / 改 SSE 既有字段 / 动 data/*。

---

## 3. AgentState 变化

原则：**全部增量、全部 Optional/带默认值**（先例：阶段 2/3 加安全字段时旧 fixture 零破坏）。任务书建议的 `confidence/evidence_ids/citations` 不单设 State 字段——它们是 diagnosis 的内部成员（citations 必须逐条挂证据 id 才可校验，抽出来反而破坏一致性）；`retrieval_result` 已携带全部 evidence id，不重复定义。

```python
# app/graph/state.py 追加（阶段 3 实施）
# —— 理解与信息充分性（decompose_question 产出）——
issue_profile: Optional[dict]
    # {"product_model": str|None, "component": str|None, "fault_type": str|None,
    #  "symptoms": list[str], "situation": str|None}
    # 机型/部件/故障与 metadata_constraints 同源同值（constraints 是其检索投影，
    # 继续供 retriever / query_log / 工单快照消费，双写不双源）。
information_sufficient: Optional[bool]     # None = 未评估（非排查类意图跳过检查）
information_gaps: Optional[list[dict]]     # [{"field": "product_model", "reason": "..."}]
followup_just_asked: Optional[bool]        # 输入字段：chat.py 依上一轮 route_path=="followup" 注入

# —— 结构化诊断（diagnose 产出，仅 local 支路）——
diagnosis: Optional[dict]                  # DiagnosisSchema 序列化（见下）

# —— 业务决策（decide_action 产出）——
recommended_action: Optional[str]          # "answer" | "followup" | "create_ticket" | "escalate"
auto_create_ticket: Optional[bool]         # chat.py 据此调用 TicketService
```

### DiagnosisSchema（`graph/tools.py` 新增，与 DecomposeSchema 同层）

```python
class DiagnosisCause(BaseModel):
    cause: str                                   # 可能原因
    status: Literal["knowledge_based", "inferred", "unverifiable"]
    evidence_ids: list[str] = []                 # 指向 retrieval_result 的 Evidence.id

class DiagnosisCitation(BaseModel):
    evidence_id: str
    document_id: str | None = None
    document_name: str                           # 与【来源：文档名】同源
    data_type: Literal["factual", "synthetic"] | None = None

class DiagnosisStep(BaseModel):
    step: str                                    # 操作步骤（官方来源）
    expected: str | None = None                  # 预期现象
    stop_condition: str | None = None            # 何时立即停止
    evidence_ids: list[str] = []

class DiagnosisSchema(BaseModel):
    summary: str                                 # 一句话问题判断（对应七段【问题判断】）
    product_model: str | None = None
    fault_type: str | None = None
    possible_causes: list[DiagnosisCause] = []   # 对应【可能原因】，保留三分标注
    recommended_steps: list[DiagnosisStep] = []  # 对应【建议排查】四要素
    safety_warning: str | None = None            # 对应【安全提醒】
    information_gaps: list[dict] = []            # 诊断后仍缺的信息（对应【需要补充的信息】）
    needs_human_service: bool = False            # 决策信号：需售后/维修介入（LLM 给，规则消费）
    confidence: float = 0.0                      # 0~1，规则消费阈值见第 7 节
    citations: list[DiagnosisCitation] = []      # 对应【来源依据】，程序校验 ⊆ evidence ids
```

与七段式的关系：**七段式自然语言回答保留**（generate_local 继续输出给用户），diagnosis 是同一内容的机器可读投影——由 diagnose 节点先产出结构，generate_local 基于结构写文本，两者同源不失配。synthetic 证据在 citations 中保留 `data_type` 标记，前端沿用"模拟案例"琥珀标注逻辑。

---

## 4. Graph 变化（Before / After）

### Before（现状，13 节点）

```text
rewrite_query → decompose_question
  ├─ 闲聊(非高风险) ──────────────▶ chitchat_node ─▶ END
  ├─ 多步 ─▶ multi_step_reason ─────────────────────────────┐
  └─ 单步 ─▶ judge_relevance                                 │
              ├─ 相关 ─▶ rag_retrieve ─▶ rag_quality_eval    │
              │             ├─ pass ─▶ generate_local ───────┤
              │             ├─ fail(未纠正) ─▶ query_corrector ─▶ rag_retrieve
              │             └─ fail(已纠正) ─▶ web_search ─▶ generate_online ─┤
              └─ 不相关 ─▶ web_search ─▶ generate_online ─────────────────────┤
                                                              ▼
                                    combined_quality_check ─┬─ pass ─▶ END
                                                            └─ fail ─▶ quality_fail ─▶ END
```

### After（16 节点，新增 3 个，既有边不动）

```text
rewrite_query → decompose_question（扩展：+信息充分性/缺口/症状 结构化输出）
  ├─ 闲聊(非高风险) ──────────────▶ chitchat_node ─▶ END
  ├─ 信息不足(见 §5 触发条件) ─▶ ask_followup ─▶ END          ★ 新节点
  ├─ 多步 ─▶ multi_step_reason ─────────────────────────────┐
  └─ 单步 ─▶ judge_relevance                                 │
              ├─ 相关 ─▶ rag_retrieve ─▶ rag_quality_eval    │
              │             ├─ pass ─▶ diagnose ─▶ generate_local ───┤  ★ 新节点
              │             ├─ fail(未纠正) ─▶ query_corrector ─▶ rag_retrieve
              │             └─ fail(已纠正) ─▶ web_search ─▶ generate_online ─┤
              └─ 不相关 ─▶ web_search ─▶ generate_online ─────────────────────┤
                                                              ▼
                                    combined_quality_check
                                                              ▼
                                    decide_action（确定性规则，无 LLM）  ★ 新节点
                                                            ─┬─ pass ─▶ END
                                                             └─ fail ─▶ quality_fail ─▶ END
```

路由函数变化只有两处：`route_after_decompose` 增加 `ask_followup` 分支（优先级低于高风险覆盖、高于多步/普通分流）；`combined_quality_check` 的条件出边改挂到 `decide_action` 之后（`route_after_decide_action` 逻辑 = 原 `route_after_combined_quality` 原样后移）。CRAG 回路、多步、闲聊、质量失败路径全部原样。

**任务书十六节示意图没有机械照搬的原因**：现图里"检索/证据评估"不是缺失环节而是成熟内核（judge_relevance + rag_quality_eval 就是 evidence evaluation），推倒重组只会破坏 409 测试与已调优的短路策略；`followup` 也不是终点前的分支而是**提前终结**——信息不足时不应付出"检索+生成+质量检查"的延迟与 token。

---

## 5. 新增 Node 规格

### 5.1 ask_followup（追问节点）

- **位置**：`route_after_decompose` 新分支 → `ask_followup` → `END`。
- **触发条件（全部满足，缺一不可）**：`information_sufficient=false` 且 `information_gaps` 非空；`intent ∈ {troubleshooting, flight_safety}`；`safety_level != high`（高风险永不追问，必须立即给保守指引——沿用提示词共同纪律 6"未知状态先询问+保守提醒"，但那发生在回答内）；`¬followup_just_asked`（上一轮已追问过，本轮必须尽力作答）；`¬user_requests_human`；`¬prior_troubleshoot_failed`；`¬needs_decomposition`；无 `attachment_evidence`（用户主动附日志/照片说明已尽力提供材料）。
- **行为**：一次 LLM 调用（MODEL_PRO_CHAT，流式——SSE token 体验一致）按 `FOLLOWUP_PROMPT` 生成**一条**针对性追问：逐条引用 `information_gaps` 的 field+reason，说明"为什么需要"，不超过 3 项缺口，禁止顺带给不确定的排查步骤（防误导）。
- **写出 State**：`final_answer=追问文本`、`route_path="followup"`、`recommended_action="followup"`、`escalation_required=false`、`information_gaps`（透传供 meta/评估）。**不进 combined_quality_check**（追问句无事实断言，质量检查是噪音），与 chitchat 同样的直连 END 模式。
- **跨轮合并**：无需专门机制——追问文本进入 history，下一轮 rewrite_query 做指代消解、decompose 重新评估充分性；`followup_just_asked` 守卫保证最多连续追问 1 轮，第 2 轮无论如何按现有纪律尽力作答（缺口内容以（无法确认）标注）。

### 5.2 diagnose（结构化诊断节点）

- **位置**：仅 local 支路，`rag_quality_eval --pass--> diagnose --> generate_local`。多步/联网路径**本期不做**结构化诊断（评估集 29/34 local 路由；先落核心路径，控制延迟与风险面）。
- **输入**：`retrieval_result`（格式化证据上下文）、`issue_profile`、`rewritten_query`、安全字段。
- **行为**：一次非流式 LLM 调用（MODEL_FLASH + `with_structured_output(DiagnosisSchema)`，先例：DecomposeSchema/CombinedQualitySchema）输出第 3 节结构。`citations.evidence_id` 必须来自 `retrieval_result[*].id`，**程序后校验**：不在集合内的 citation 直接丢弃；全被丢弃则 `confidence` 置 0（证据与结论脱钩视为不可信）。
- **容错**：LLM 失败/超时/结构非法 → `diagnosis=None`，generate_local 退回现行纯文本行为，流程不中断（先例：decompose 失败降级）。
- **七段式不废弃**：`LOCAL_GEN_PROMPT` 追加 `【结构化诊断（供校对，不得与本内容冲突）】{diagnosis}` 段（注入值在 `.format()` 之后拼接或作为参数传入均可，模板不引入裸花括号——现有安全模式），generate_local 照常流式输出七段文本。延迟预算：+1 次 flash 调用 ≤1.5s（非流式与 token 流并行无冲突——diagnose 在 generate 之前完成，用户感知为 stage 多亮一格）。

### 5.3 decide_action（业务决策节点，确定性规则，零 LLM）

- **位置**：`combined_quality_check --> decide_action --(route_after_decide_action)--> END / quality_fail`。所有路径（local/online/decomposition）经过。
- **决策阶梯（优先级从高到低，首条命中即返回）**：

```text
G0  escalate：user_requests_human ∨ prior_troubleshoot_failed ∨ safety_level=high
            ∨ 低置信（local: diagnosis 缺失 ∨ diagnosis.confidence < 0.4 ∨ avg_reranker_score < 0.45
                      ∨ 无有效证据；online: search_failed；decomposition: 上下文为空）
    → recommended_action="escalate"；escalation_required=True（向后兼容现有字段）
    → auto_create_ticket = user_requests_human ∨ prior_troubleshoot_failed
      （用户明确要人工、或已确认两轮排查无效 → 介入是必然，自动建草稿；
       高风险首轮不自动建单——可能只是安全咨询，一答即解，保持现有横幅+按钮由用户决定）
    → 本分支下 quality fail 照旧挂警告（不覆盖答案）

G1  followup：route_path=="followup"（ask_followup 节点已置，decide_action 仅透传）

G2  create_ticket：¬escalate ∧ information_sufficient ∧ intent ∈ {troubleshooting, flight_safety}
                 ∧ diagnosis.needs_human_service=True ∧ diagnosis.confidence ≥ 0.55
                 ∧ route_path=="local"
    → recommended_action="create_ticket"；auto_create_ticket=True
    （needs_human_service 由诊断 LLM 给出——如摔损/进水/硬件更换史/官方文档明示送修情形——
     但最终是否建单由本确定性规则裁决，LLM 无权直接决定）

G3  answer：默认值（含 quality fail 但可回答的情形——警告横幅照旧）
```

- **写出 State**：`recommended_action`、`auto_create_ticket`、`escalation_required`（兼容字段同步维护），并向 `judge_log` 追加一条 `{judge_type: "decide_action", passed: true, raw_output: {action, 触发规则, 信号快照}}`——进入 TraceTimeline 与评估口径。
- **不放在图外的理由**：决策必须出现在 trace 时间线（前端逐节点点亮）与 judge_log（评估可测）；**建单副作用不放图内**：图保持纯函数，chat.py 在 final_state 之后调用 TicketService（见第 8 节），与 fault_progress 同为"chat 层管业务胶水"的既有模式。

---

## 6. 新增 Route（路由函数）

| 路由 | 变化 |
|---|---|
| `route_after_decompose` | 分支优先序：①高风险覆盖闲聊（现有）→ ②**followup 条件命中 → "ask_followup"** → ③多步 → ④judge_relevance。ask_followup 的完整守卫条件见 §5.1，条件计算抽成纯函数 `_should_followup(state)` 便于单测 |
| `route_after_rag_quality` | **不变**（CRAG 回路原样） |
| `route_after_decide_action`（新） | 逻辑 = 原 `route_after_combined_quality` 原样后移：无幻觉且质量通过 → END，否则 → quality_fail |

---

## 7. Tool / Service 设计

**graph/tools.py**：新增 `DiagnosisSchema` 系列模型；`FOLLOWUP_PROMPT / DIAGNOSE_PROMPT` 进 prompts.py。`call_llm/evaluate/retrieve/tavily_search` 零改动（retrieve 已支持 top_k/constraints/priority 参数化，诊断与管理端分析直接复用）。

**新 Service：`app/services/ticket_analysis_service.py`**（管理端 Copilot 编排，图外、同步）：

```text
analyze_ticket(ticket_id) ->
  1. 聚合上下文：ticket 行 + ticket_events(公开+内部) + ticket_evidence
     + 关联 conversation 的 messages + query_log（含历史 diagnosis_json/来源）
     + 证据附件文本（attachment_store 读取，仅 ready 状态；内容不出现在持久化结果）
  2. 组装 issue_profile：快照字段（device_model/fault_category）优先，
     缺失时一次 LLM 补全（复用 DecomposeSchema 的 product_model/component/fault_type 字段）
  3. 检索：RAGRetriever.retrieve(query=摘要+现象, metadata_constraints=issue_profile 投影,
     document_type_priority=按 intent 映射)——与聊天路径同一检索器、同一过滤策略
  4. 诊断：call_llm + AdminAnalysisSchema（DiagnosisSchema 超集，另加
     handling_advice: list[str]、suggested_reply: str、risk_flags: list[str]）
  5. 程序安全过滤（§13 规则）+ citations 校验（⊆ evidence ids）
  6. 返回结构化结果；由 API 层决定是否持久化为 agent_suggestion 事件（§11）
```

不新建 AgentTicketService/NewTicketService/AgentTicketTable。**一个工单系统、一个状态机、一个事实源**：Agent 建单走 `TicketService.create_draft_from_conversation(user.id, conversation_id, actor_type="agent", actor_id=None)`——该签名今日即可用，服务层零改动。

---

## 8. TicketService 接入方式（Agent 建单）

```text
decide_action（图内，纯规则）
  → final_state.recommended_action / auto_create_ticket
  → chat.py 图运行结束、assistant 消息与 query_log 落库之后：
      if final_state.get("auto_create_ticket"):
          try:
              ticket = await ticket_service.create_draft_from_conversation(
                  user.id, body.conversation_id, actor_type="agent", actor_id=None)
              meta["agent_ticket"] = {"id":..., "ticket_number":..., "status":"draft"}
          except Exception: logger.warning(...)   # 建单失败绝不阻断聊天流
```

设计要点：

1. **草稿而非提交**：agent 只能创建 `status="draft"` 的工单，提交永远由用户点击（`USER_TRANSITIONS`），管理端处理流程不变。draft 会出现在管理队列——这是特性（管理员可见"Agent 认为需要介入"），且 `draft → cancelled` 转换允许管理员一键清理误报。
2. **幂等**：每会话一张工单的 UNIQUE 约束天然防刷（重复调用返回既有工单）。
3. **audit**：`created` 事件 `actor_type="agent"` 自动落入 ticket_events，管理端时间线可见 agent 分色条目。
4. **边界**：agent 依旧不能 transition 任何状态（`ticket_service.py:465-466` 禁令不放宽）、不能关高风险单（:460-464 不放宽）、不能写 internal_note（`add_internal_note` 仅 admin）。
5. meta 新增 `recommended_action` 与 `agent_ticket` 两个可选字段（旧前端忽略未知字段——chat.py:424 注释确认的兼容先例）。

---

## 9. 管理端 Copilot 架构

```text
AdminTicketDetail.vue（现有组件内嵌面板，不新建页面/不新建路由）
┌────────────────────────────────────────────┐
│ 工单信息（现有区域不动）                      │
├────────────────────────────────────────────┤
│ AI 售后分析                    [重新分析]    │
│  问题摘要 / 产品型号 / 故障类型               │
│  AI 诊断（summary + possible_causes 三分标注）│
│  证据（document_name/机型/data_type/分数，    │
│        synthetic 琥珀标注，复用 SourceCard 字段规范）│
│  处理建议 handling_advice                    │
│  安全提示 safety_warning/risk_flags          │
│  建议回复 suggested_reply                    │
│  [采用建议] → 预填到现有"公开回复"输入框       │
│  （高风险单：红色横幅"AI 建议仅供参考，        │
│    必须人工确认，禁止直接发送"）               │
└────────────────────────────────────────────┘
数据来源：GET /api/admin/tickets/{id} 已返回 events——
最新一条 agent_suggestion 事件的 metadata 即分析结果，打开详情即见，零额外请求；
[重新分析] → POST ai-analysis（返回并写入新 agent_suggestion 事件，历史保留可追溯）。
```

- **AI 不自动发送任何内容**：采用建议 = 前端把 `suggested_reply` 预填进现有回复框，管理员修改后经**现有** `POST .../events (public_reply)` 发送；"处理结论"仍走现有 PATCH。human-in-the-loop 边界与任务书第十二、十三节一致。
- FE 变更集中在：`types/index.ts`（+2 类型）、`api/adminTickets.ts`（+1 函数）、`AdminTicketDetail.vue`（+面板）、`AdminTicketQueue.vue` 不动。

---

## 10. API 设计

命名核对：现有管理端子资源动作为 kebab-case（`from-conversation`、`confirm-resolution`、`reopen`），故采用：

```http
POST /api/admin/tickets/{ticket_id}/ai-analysis        # admin 角色守卫（沿用 get_current_admin_user）
  200 → {
    "ticket_id": "...", "analyzed_at": "...", "model": "deepseek-chat",
    "summary": "...", "product_model": "...", "fault_category": "...",
    "diagnosis": { ...DiagnosisSchema... },
    "knowledge": [ {Evidence 公开字段...} ],          # 含 synthetic 标注
    "sop_recommendations": [ {Evidence...} ],          # document_type=sop 子集
    "handling_advice": ["..."], "safety_warnings": ["..."],
    "suggested_reply": "...", "confidence": 0.72,
    "high_risk": false, "disclaimers": ["AI 分析仅供参考，最终处理以人工确认为准"]
  }
  错误：404 工单不存在 / 422 上下文不足（无任何可分析内容）/ 504 分析超时（降级文案）
```

同步返回（v1，管理端 spinner 数秒可接受；流式化留作后续优化，不阻塞主线）。**无新增 GET**：分析结果经 events 随现有详情接口下发。用户侧 API 零新增（Agent 建单复用现有草稿链路，用户经 `/api/tickets` 看到并提交）。

---

## 11. 数据流（端到端）

```text
【聊天侧 · 工单前】
用户消息 → chat.py：fault_progress 计数（现有）→ get_history(+route_path 列)
        → followup_just_asked 注入 input_state
        → 16 节点图执行（stage/token/node_end 照旧；diagnose/decide_action 各亮一格）
        → final_state：diagnosis / recommended_action / information_gaps
        → assistant 消息落库（route_path 已含 followup）+ query_log 落库（+2 列）
        → auto_create_ticket ? TicketService 建草稿(actor=agent)
        → SSE meta：+recommended_action / +issue_profile / +information_gaps
                    / +diagnosis（公开字段） / +agent_ticket?
        → 前端：action=create_ticket → "已生成工单草稿"横幅+跳转；
                action=followup → 追问即 normal 消息渲染（零新组件也可）
                action=escalate → 现有升级横幅+按钮（不变）

【管理侧 · 工单后】
管理员打开 AdminTicketDetail → 现有 GET detail（events 已含历史 agent_suggestion）
  → 面板渲染最新分析；[重新分析] → POST ai-analysis
  → ticket_analysis_service：工单上下文 → 检索 → AdminAnalysisSchema → 安全过滤
  → 返回 JSON + 追加 ticket_events(actor_type=agent, event_type=agent_suggestion,
     body=一句话摘要, metadata=分析 JSON)
  → [采用建议] 预填公开回复框 → 人工发送（现有 POST events public_reply）
```

---

## 12. 持久化策略

### 12.1 聊天侧新增持久化（列，不是表）

| 存储 | 变更 | 用途 |
|---|---|---|
| `query_log` | +2 可空列：`recommended_action TEXT`、`diagnosis_json TEXT`（PRAGMA 缺列 ALTER，先例：fault_key/safety 列） | 评估（action_accuracy/diagnosis 指标）、管理端分析的历史上下文、问题回流 |
| `messages` | **零 schema 变更**（route_path 列已存在且已持久化） | followup_just_asked 守卫数据源 |
| `conversation_store.get_history` | SELECT 增加返回 `route_path`（只读查询扩展，`{role,content}` 消费方不受影响） | 同上 |

### 12.2 管理端分析持久化：A/B/C 方案对比与推荐

| 方案 | 优点 | 缺点 |
|---|---|---|
| A 每次点击重新生成，不落库 | 零存储、永远最新 | 每次数秒+token 成本；无审计；管理员之间不可共享；刷新即丢 |
| B **写入 ticket_events**（actor_type=agent, event_type=agent_suggestion, body=摘要, metadata=完整分析 JSON） | 复用只追加审计流水（正是该表职责）；前端"AI 建议"文案映射与 agent 分色已就位；最新分析=最新事件、历史分析天然留痕可追溯；用户侧只需把 `agent_suggestion` 加进 `_INTERNAL_EVENT_TYPES`（api/tickets.py:28 现有过滤机制）；**零新表零新 store** | events 增长（有界：仅手动重分析时追加）；metadata JSON 需设大小上限（截断证据正文，只留 id/标题/分数） |
| C 新增 ai_analyses 表 | 可独立索引/清理 | 新 store+迁移+生命周期管理；与审计事件重复记录同一事实；违背"不为架构完整加表" |

**推荐 B**。理由：分析的审计价值与工单事件表职责完全重合（谁/何时/基于什么给出了什么建议）；FE 插槽与 agent 角色授权已预留；实施面最小。配套约束：metadata 只存结构化结论与证据指针（id/标题/分数/机型/data_type），不存附件正文与全文；单条 metadata 序列化上限 32KB，超限截断证据列表。

---

## 13. 安全策略

| 情形 | 处理（现有机制 + 新增规则） |
|---|---|
| 高风险（safety_level=high） | 永不 followup（§5.1 禁止）；`SAFETY_EMERGENCY_DIRECTIVE` 照旧拼接（分态处置：飞行中只给返航/降落指引，禁空中断电）；decide_action 必 escalate；**不自动建单**（首轮安全咨询可能一答即解，按钮留给用户）；管理端分析对高风险单：`handling_advice` 降级为保守清单（隔离/勿充电/勿拆解/联系官方），`suggested_reply` 只含安抚+安全指引+转人工话术，FE 红横幅 |
| 危险维修操作（拆机/带电维修/绕过安全/改装） | 提示词共同纪律已禁止；**管理端分析服务加程序后过滤**：`risk_flags` 命中 `_SAFETY_KEYWORDS`（nodes.py:68 词表复用）时，剥离 `recommended_steps` 中无官方证据来源（citations 为空）的步骤，只保留官方文档直接支持的步骤 |
| 低置信 / 证据不足 | 现有 <0.45 升级阈值保留；diagnosis.confidence<0.4 亦触发 escalate；管理端分析 confidence<0.5 时 `suggested_reply` 降级为固定模板（"暂无法可靠判断，建议联系官方售后检测"），不给具体结论 |
| 知识冲突（同问题多文档矛盾） | diagnose 提示词要求在 possible_causes 中并列呈现冲突来源并标注证据 id（不擅自裁决）；citations 保留全部冲突文档；confidence 上限 0.5（冲突即中低置信 → 倾向 escalate/人工）；管理端面板原样展示冲突双方，交人工裁决 |
| 跨型号 | issue_profile.product_model 仅接受文本别名命中（现有保守规则 intent.py:102-105 不放宽）；检索硬过滤+通用回退不改动；diagnosis.product_model 与 profile 不一致时以 profile 为准并记 judge_log 警告；管理端分析对"快照机型 vs 证据机型"不一致的工单显式 risk_flag |
| synthetic 证据 | 永不作确诊依据：citations 保留 data_type，FE 琥珀标注；diagnose/AdminAnalysis 提示词明确 synthetic 只可作排查思路；needs_human_service 判定不得以 synthetic 案例为唯一依据 |
| 表述红线 | 沿用 7 项既有纪律（禁"已确认安全"、禁"已转人工/已建单"话术——注意：Agent 真的建单后，对用户的话术升级为"已为你生成工单草稿（待你确认提交）"，措辞模板进 FOLLOWUP/生成提示词，仍禁止宣称"已通知工程师/已受理"） |

---

## 14. 评估方案

**数据集**：`build_dataset.py` 扩容至约 50 题（34 现有 + 新场景），新类别与 gold 动作：

| 新类别 | 示例 | gold recommended_action |
|---|---|---|
| insufficient_info（×5） | "我的无人机飞不了了" / "它充不进电"（无机型+现象模糊） | followup |
| insufficient_info_second_turn（×2） | 追问后用户补充机型+现象 | answer / create_ticket（非 followup 即过） |
| service_needed（×4） | "摔了之后图传黑屏" / "换了 GPS 还是不定位" | create_ticket |
| high_risk（×3，并入现有 6 题安全题的 gold 动作） | "电池充电时鼓包了" | escalate |
| knowledge_conflict（×2） | 构造同故障两文档结论分歧的问题 | escalate 或 answer+citations 冲突标注 |
| cross_model（沿用现有 3 题 + 1 新题） | Mini 4 Pro 问 Matrice 参数 | answer 且无污染 |

**新指标**（run_eval.py 注册表追加，消费 meta.recommended_action/diagnosis）：

```text
action_accuracy                    # recommended_action vs gold
followup_gap_hit_rate              # followup 轮次中 information_gaps 与 gold gaps 的命中率
ticket_action_accuracy             # auto_create_ticket 触发与否 vs gold（含误报率）
diagnosis_citation_validity        # citations ⊆ evidence ids 的比例（真实性硬校验）
diagnosis_coverage                 # possible_causes/recommended_steps 非空率
（既有 route/intent/product_model/safety_recall/escalation_accuracy/
  cross_model_contamination 全部保留作回归门）
```

**回归门**：现有 34 题 route/safety/escalation 指标不得劣化；`gold_status=inferred` 的诚实标注机制延续，新题 gold 需人工复核后置 `verified`（机制已支持）。

---

## 15. 影响文件列表

### 需要修改（后端）

| 文件 | 变更 |
|---|---|
| `app/graph/state.py` | +7 字段 |
| `app/graph/tools.py` | +DiagnosisSchema 系列；DecomposeSchema +3 字段（information_sufficient/information_gaps/symptoms，带默认值） |
| `app/graph/prompts.py` | DECOMPOSE_PROMPT 扩充分泌性字段说明；+FOLLOWUP_PROMPT、+DIAGNOSE_PROMPT；LOCAL_GEN_PROMPT +diagnosis 注入段 |
| `app/graph/nodes.py` | decompose 扩展；+ask_followup_node、+diagnose_node、+decide_action_node；generate_local 消费 diagnosis（容错降级） |
| `app/graph/builder.py` | +3 节点、+2 边组、route_after_decompose 分支、combined 出边改挂 decide_action |
| `app/api/trace.py` | STAGE_LABELS +3 中文标签；TRACE_OUTPUT_FIELDS +3 节点白名单（漏加不崩：有兜底文案，但必须补齐保证体验） |
| `app/api/chat.py` | input_state +followup_just_asked；图后建单胶水；meta +4 可选字段；query_log 新列写入 |
| `app/api/admin_tickets.py` | +1 路由 ai-analysis |
| `app/api/tickets.py` | `_INTERNAL_EVENT_TYPES` + `agent_suggestion`（用户侧不可见） |
| `app/services/ticket_analysis_service.py` | **新建** |
| `app/services/conversation_store.py` | get_history SELECT +route_path（只读扩展） |
| `app/services/query_log_service.py` | +2 可空列迁移与写入 |
| `app/main.py` | 分析 service 装配；（顺手）FastAPI title 残留修正 |

**零修改**：`rag/*`（indexer/retriever/reranker/readers/embedding/graph_builder）、`graph/intent.py`、`graph/state.py` 以外的既有字段、`services/ticket_service.py`、`services/ticket_store.py`、`services/fault_progress_service.py`、auth/attachments/feedback 全链路、`data/*` 全部。

### 需要修改（前端，阶段 5/6 实施）

| 文件 | 变更 |
|---|---|
| `types/index.ts` | +ChatMeta 新字段、+AgentAnalysis 类型 |
| `stores/chat.ts` | meta 新字段绑定 |
| `components/AssistantMessage.vue` | create_ticket 横幅（草稿已生成+查看按钮）、followup 沿用普通渲染 |
| `components/AdminTicketDetail.vue` | AI 分析面板（渲染最新 agent_suggestion 事件 + 采用/重新分析） |
| `api/adminTickets.ts` | +aiAnalysis 函数 |
| `components/JudgeBadges.vue` | route_path="followup" 徽章 |

### 测试（新增/调整）

unit：`test_decide_action.py`（决策阶梯全覆盖）、`test_followup.py`（守卫矩阵）、`test_diagnosis_schema.py`（citations 校验/降级）；`test_nodes.py`/`test_state.py`/`test_builder.py` 增补；`test_chat_meta` 增补（meta 兼容性：旧字段不变）。integration：`test_api_tickets.py` 增补（agent_suggestion 用户侧过滤）、`test_api_admin.py` 增补（ai-analysis 鉴权/404/持久化事件）。前端：AdminTicketDetail 面板、chat store meta、AssistantMessage 横幅。**既有 409+99 全部保持绿。**

---

## 16. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 追问误触发骚扰用户（把可答问题拦下反问） | 触发面收窄（仅 troubleshooting/flight_safety）；单轮上限 1 次；`followup_just_asked` 硬守卫；高风险/要求人工/排查失败/附件在场全部豁免；`AGENT_FOLLOWUP_ENABLED` 开关可即时关闭 |
| R2 | local 路径延迟 +1 次 LLM（diagnose） | 用 MODEL_FLASH 非流式 ≤1.5s；失败即降级 None（回现行行为）；followup 反而**省**后续 4-5 次调用 |
| R3 | DecomposeSchema 扩展破坏既有单测严格断言 | 新字段全带默认值（旧 fixture 可解析）；实施前先跑全量基线，逐个修正断言而非放松校验 |
| R4 | 自动建单产生垃圾草稿 | needs_human_service ∧ confidence≥0.55 双门槛；每会话幂等 1 张；管理员可 draft→cancelled；`AGENT_AUTO_TICKET_ENABLED` 开关 |
| R5 | agent_suggestion 事件泄敏感内容/过大 | 用户侧 `_INTERNAL_EVENT_TYPES` 过滤；metadata 只存结论+证据指针，32KB 上限截断 |
| R6 | SSE 协议兼容性破坏 | 只增字段不改既有字段（chat.py:424 确认旧前端忽略未知字段）；SSE 事件类型零新增 |
| R7 | LLM citations 幻觉 | 程序校验 ⊆ evidence ids，非法即弃、全弃则 confidence=0 |
| R8 | 管理端分析对高风险单给维修步骤 | §13 后过滤 + 降级模板 + FE 红横幅；AI 永不自动发送 |
| R9 | 知识冲突被 LLM 擅自裁决 | 提示词强制并列呈现 + confidence 封顶 0.5 + 倾向人工 |
| R10 | 评估 gold 全 inferred 造成的假阳性 | 新增指标先行、结论仅用于回归对比不做质量承诺（延续诚实声明传统） |

---

## 17. 回滚方案

1. **运行时开关（第一道）**：config.py 新增 3 个布尔（默认 False，验收后置 True）：`AGENT_FOLLOWUP_ENABLED`（关=decompose 永不输出 followup 分支）、`AGENT_AUTO_TICKET_ENABLED`（关=chat.py 跳过建单胶水）、`ADMIN_AI_ANALYSIS_ENABLED`（关=路由 404/503）。改配置重启即回旧行为，diagnosis/decide_action 残留字段无害（meta 旧前端本就忽略）。
2. **提交粒度（第二道）**：阶段 3/4/5/6 各自独立 commit（先例：工单 Task 1-8 每 Task 一笔），可逐个 `git revert`；阶段 4 revert 后 diagnose 不在图中，generate_local 走原提示词。
3. **数据（第三道）**：全部持久化为**可空列追加 + 只追加事件**，无需回滚迁移；agent_suggestion 历史事件保留不影响任何流程；query_log 新列留空即可。
4. **绝不回滚**：工单状态机、RAG 内核、既有测试断言不因回滚改动（回滚只动新增代码）。

---

## 18. 验收标准

**全局红线（每阶段结束都验）**：`pytest` 全绿（409+新增）、`npm test` 全绿（99+新增）、`npm run build` 通过、`compileall` 通过；手工冒烟：SSE 流式+TraceTimeline+来源卡片正常；**客户端建草稿→提交→管理端接单/回复→用户确认关闭**全链路无回归；高风险工单仍无法被 agent/system 关闭。

| 阶段 | 交付 | 验收标准 |
|---|---|---|
| 阶段 3：State+Graph+追问 | §3/§4/§5.1 落地 | ①"我的无人机飞不了了"→ route_path=followup、gaps 含机型/现象、SSE 正常流式；②同一会话连续第二轮不再追问（尽力作答+（无法确认）标注）；③"电池鼓包"等高风险题永不 followup 且走紧急指令；④闲聊/参数题/多步题零行为变化；⑤meta 含新字段且旧字段值不变；⑥`_should_followup` 守卫矩阵单测全绿 |
| 阶段 4：诊断+决策 | §5.2/§5.3 落地 | ①local 路径 diagnosis 结构完整、citations 100% ⊆ evidence ids、七段文本与 diagnosis 不冲突（抽样）；②decide_action 阶梯单测覆盖全部 G0-G3 分支与边界（confidence 阈值两侧、followup_just_asked、多步/联网路径降级）；③escalation_required 在旧触发场景下取值与改造前一致（回归对比）；④diagnose 失败注入测试：回答照常产出 |
| 阶段 5：Agent 建单 | §8 落地 | ①service_needed 类问题触发草稿创建，actor_type=agent 落审计事件；②重复触发幂等（仍 1 张）；③高风险首轮不自动建单但 escalate 横幅照旧；④用户对 agent 草稿可编辑/提交/取消，管理端可见可处理；⑤建单失败注入测试不阻断聊天流；⑥既有工单测试零修改全绿 |
| 阶段 6：管理端 Copilot | §9/§10/§12.2 落地 | ①端点仅 admin 可用（普通用户 401/403，跨工单 404）；②分析返回结构完整并持久化为 agent_suggestion 事件，用户侧详情接口不可见；③[采用建议]仅预填回复框、发送仍是人工动作；④重新分析追加事件且历史可追溯；⑤高风险单 advice/reply 已降级+红横幅；⑥超时/LLM 失败返回 504 与降级文案，不 500 |
| 阶段 7：评估 | §14 落地 | ①新类别题目入集且 gold 完整；②action_accuracy/ticket_action_accuracy/diagnosis_citation_validity 出数；③既有 34 题回归指标不劣化；④评估报告诚实标注 gold_status 与执行环境 |

---

## 19. 推荐开发顺序（等待授权）

```text
阶段 3  State 扩展 + decompose 扩展 + ask_followup + 路由分支 + trace 白名单
        → 独立可交付：追问能力上线（最小可感知增量）
阶段 4  diagnose 节点 + decide_action 节点 + generate_local 消费诊断 + query_log 扩列
        → 独立可交付：结构化诊断与决策出数（meta 可见，前端可暂不渲染）
阶段 5  chat.py 建单胶水 + meta.agent_ticket + AssistantMessage 横幅（FE 最小面）
        → 独立可交付：Agent 建单闭环
阶段 6  ticket_analysis_service + admin API + AdminTicketDetail 面板 + tickets.py 过滤
        → 独立可交付：管理端 AI Copilot
阶段 7  数据集扩容 + run_eval 新指标 + 回归报告
```

每阶段实施前按工作区规则先出该阶段的六要素确认单（影响文件/数据流/风险/验收已在本文 §15-§18，实施单只需细化到函数级 diff 计划），获得明确授权后再动代码。
