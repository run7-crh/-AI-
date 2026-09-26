# Agent 增量改造实施报告（最终交付）

- 日期：2026-09-26
- 分支：`codex/auth-admin`
- 基线：`464cb53`（Stage 0 验证：后端 413 / 前端 111 全绿）
- 最终：后端 **488 passed** / 前端 **116 passed** / vue-tsc build 通过 / compileall 通过
- 设计依据：[target_architecture.md](target_architecture.md)；事实基础：[current_system_audit.md](current_system_audit.md)
- 约束核对（git diff 464cb53..HEAD）：`app/rag/*`、`ticket_service.py`、`ticket_store.py`、`fault_progress_service.py`、`auth_store.py`、`attachment_store.py`、`data/*` **零改动**——增量改造承诺兑现

## 1-2. 改造前 / 改造后架构

改造前（详见审查报告）：13 节点固定拓扑 Corrective RAG + 单向快照式工单连接 + 纯手工管理台。

改造后（**16 节点 + 5 路由**，全部增量）：

```text
rewrite_query → decompose_question（扩展：+信息充分性/缺口/症状/issue_profile）
  ├─ 闲聊(非高风险) ─→ chitchat_node ─→ END
  ├─ 信息不足（AGENT_FOLLOWUP_ENABLED 且守卫通过）─→ ask_followup ─→ END   ★ 新
  ├─ 多步 ─→ multi_step_reason ─────────────────────────────────────────┐
  └─ 单步 ─→ judge_relevance                                             │
              ├─ 相关 ─→ rag_retrieve ─→ rag_quality_eval                │
              │             ├─ pass ─→ diagnose ─→ generate_local ───────┤  ★ diagnose 新
              │             ├─ fail(未纠正) ─→ query_corrector ─→ rag_retrieve
              │             └─ fail(已纠正) ─→ web_search ─→ generate_online ─┤
              └─ 不相关 ─→ web_search ─→ generate_online ─────────────────────┤
                                     combined_quality_check                    │
                                             ↓                                 │
                                     decide_action（零 LLM 确定性规则）★ 新      │
                                       ├─ 质量通过 ─→ END                       │
                                       └─ 失败 ─→ quality_fail ─→ END ◄────────┘
图运行后（chat.py 胶水）：auto_create_ticket → 现有 TicketService 建 draft（actor=agent）
管理端：POST /api/admin/tickets/{id}/ai-analysis → TicketAnalysisService（复用检索器）→ agent_suggestion 事件
```

## 3. Graph 变化

- 新增 3 节点：`ask_followup`（decompose 分支→END，不检索不质检）、`diagnose`（仅 local 支路，rag_quality_eval 通过后、generate_local 前，MODEL_FLASH 结构化输出）、`decide_action`（combined_quality_check 之后，全部生成路径必经）。
- 路由变化仅两处：`route_after_decompose` 增加追问分支（优先级低于高风险覆盖）；combined 的条件出边后移到 decide_action 之后（逻辑不变）。
- CRAG 回路、多步、闲聊、质量失败路径零改动。

## 4. State 变化

新增 9 个全 Optional 字段：`issue_profile / information_sufficient / information_gaps / followup_just_asked / recommended_action / diagnosis / auto_create_ticket`（+ diagnosis 内含 confidence/citations/needs_human_service）。与 `metadata_constraints` 同源不双写；旧 fixture 零破坏。

## 5. Followup（信息充分性 + 主动追问）

- `DecomposeSchema` +3 字段（information_sufficient/information_gaps/symptoms，带默认值）。
- `_should_followup` 九条件守卫矩阵（意图 ∈ troubleshooting/flight_safety、非高风险、未连续追问、无附件、未要求人工、未排查失败、非多步）。
- `ask_followup_node`：流式生成追问（安全提醒前置 + 逐条解释为什么问），失败降级静态追问；追问轮 `route_path="followup"` 直接 END。
- 跨轮机制：`get_history` 返回 route_path → chat.py 注入 `followup_just_asked` → 最多连续追问 1 轮，第二轮必须尽力作答。

## 6. Diagnosis（结构化诊断）

- `DiagnosisSchema` 家族（cause 三分标注 / step 四要素 / citation 带 data_type）。
- 引用程序校验：citations ⊆ retrieval evidence ids，非法即弃、全无则 confidence 归零——LLM 无法编造证据 id（真实评估中 23/23 全部有效）。
- `generate_local` 保留七段式，结构化诊断以"校对块"注入（format 后拼接，花括号安全）；诊断失败降级 None，回答照常。

## 7. Decision（确定性业务决策）

G0 escalate（要求人工∨排查失败∨高风险∨按路由的低置信）→ G1 followup 透传 → G2 create_ticket（充分 ∧ 排查意图 ∧ local ∧ needs_human_service ∧ confidence≥0.55 ∧ 质量未判失败）→ G3 answer。LLM 只供给信号，action 由规则裁决；judge_log 记录触发规则与信号快照（可进 TraceTimeline 与评估）。

## 8. Agent Ticket（复用现有工单系统）

chat.py 在消息与 query_log 落库后调用 `TicketService.create_draft_from_conversation(actor_type="agent")`——**ticket_service/ticket_store 零改动**。只建 draft（提交仍是用户动作）、每会话幂等、失败仅告警不阻断 SSE、高风险首轮不自动建单。真实评估：45 题中 **0 误建单**。

## 9. Admin Copilot（管理端 AI 售后分析）

- `TicketAnalysisService`：聚合工单/事件/证据/会话/query_log → 复用生产 `RAGRetriever`（无第二套检索）→ `AdminAnalysisSchema`（诊断+处理建议+回复草稿+风险旗标）→ 安全过滤（高风险强制保守清单/模板，低置信降级保守回复）。
- `POST /api/admin/tickets/{id}/ai-analysis`：admin-only；结果持久化为 `agent_suggestion` 事件（追加式审计，32KB metadata 上限）；用户侧经 `_INTERNAL_EVENT_TYPES` 不可见。
- `AdminTicketDetail.vue` 内嵌 AI 面板（打开详情零额外请求，渲染最新事件）；**采用建议=仅预填公开回复框，发送仍是人工动作**；重新分析追加事件，历史可追溯。

## 10. 数据库变化

无新表。`query_log` +2 可空列（`recommended_action`、`diagnosis_json`，PRAGMA 缺列迁移先例）；`get_history` SELECT 增加返回 route_path（只读扩展）；`tickets` 表 serial_number/firmware_version 预留字段保持空置。新增事件类型 `agent_suggestion`（actor_type=agent）。

## 11. API 变化

新增 1 个端点：`POST /api/admin/tickets/{ticket_id}/ai-analysis`（401/403/404/422/503/504 映射完整）。SSE meta 新增可选字段：`recommended_action / information_gaps / diagnosis / agent_ticket`（旧前端忽略未知字段，协议向后兼容）。其余端点零变化。

## 12. 前端变化

`JudgeBadges`（+chitchat/followup 徽章）、`AssistantMessage`（Agent 建单横幅+查看按钮，不自动提交）、`AdminTicketDetail`（AI 分析面板+采用/重新分析）、`types/index.ts`、`stores/chat.ts`、`api/adminTickets.ts`。无新页面、无新路由。

## 13. 安全策略（实施落实）

高风险永不追问、紧急处置指令沿用、高风险首轮不自动建单、agent/system 禁止一切状态转换（未放宽）、synthetic 证据仅作思路参考（citations 保留 data_type + FE 琥珀标注）、危险维修建议被保守清单程序性覆盖（管理端）、诊断引用程序校验、agent_suggestion 用户侧不可见、AI 永不自动发送/关闭工单。

## 14. Evaluation（真实在线基线，详见 [agent_upgrade_eval.md](../evaluation/agent_upgrade_eval.md)）

数据集 v2.1（47 题）；45 题真实执行 + 2 题多轮跳过。核心数字：action_accuracy 65.1%、ticket_action_accuracy 86.7%（误报 0）、followup_gap_hit_rate 90%、diagnosis_coverage 100%、diagnosis_citation_validity 100%、safety_recall 100%、cross_model_contamination 0、route_accuracy 68.9%（首次无人机版真实基线，改造前从未真实跑通——评估脚本缺登录逻辑属既有缺陷，本次修复）。

## 15. 测试结果

后端 **488 passed**（基线 413 + 新增 75：test_followup 24 / test_diagnosis_schema+decide_action 35 / test_ticket_analysis_service 6 / test_api_agent_ticket 6 / test_api_ai_analysis 4 / test_eval 调整）/ compileall 通过；前端 **116 passed**（+3 组件测试）/ vue-tsc + vite build 通过。

## 16. 失败案例（评估真实暴露，未掩盖）

6 道 answer→escalate 误报（非排查意图也触发低置信升级链，保守方向但伤体验）；4 道 service_needed 全漏报（2 道误入 followup、2 道误路由 online——时效词表把"升级固件"当求证）；"已排查两次"类题 decompose 未把自述排查历史当升级信号。完整分析见评估报告 §4。

## 17. 性能/延迟变化

local 路径 +1 次 MODEL_FLASH 非流式调用（diagnose，预算 ≤1.5s）；追问路径反而省去检索+生成+质检约 3-4 次调用；decide_action 零 LLM 成本；管理端分析按需触发（数秒级，同步返回）。本次未做系统性延迟压测（列为已知限制）。

## 18. 已知限制

1. 全部评估 gold 为 inferred 未人工复核；action_accuracy 的 gold 本身可能有偏差。
2. 多轮追问后场景未自动化验证（2 题 skipped_multi_turn）。
3. 评估期间自动建单会写库（本次用隔离临时库并已删除；正式环境需注意）。
4. 未做延迟压测与并发验证；管理端分析为同步接口（大工单可能数秒）。
5. README 未更新本次改造内容（18 节模板版本仍有未提交修改待用户定夺，为避免混入本次提交未触碰）。

## 19. 后续规划

按评估报告 §6 优先级：非排查意图的决策口径修正（预计 action_accuracy +10pt）→ decompose 充分性提示词迭代 → 时效词表拆分 → service_needed 场景回流 → gold 人工复核 → 真实问题回流。

## Git 提交清单

| Commit | 阶段 | 内容 |
|---|---|---|
| `e20d322` | stage0-baseline | 基线验证 + 审查/设计文档入库 |
| `413c64a` | stage3-followup | 信息充分性 + ask_followup + 守卫矩阵（24 测试） |
| `a61b482` | stage4-diagnosis-decision | DiagnosisSchema + diagnose/decide_action + query_log 扩列（35 测试） |
| `c62f4c8` | stage5-agent-ticket | Agent 建单胶水 + meta.agent_ticket + 前端横幅（8 测试） |
| `ca528d6` | stage6-admin-copilot | 分析服务 + ai-analysis API + AI 面板（13 测试） |
| `e81ea13` | stage7-evaluation | 数据集 v2.1 + 新指标 + 首份真实基线 + 评估报告 |
| （本次） | final-review | 开关默认启用 + FastAPI 标题修正 + 实施报告 |
