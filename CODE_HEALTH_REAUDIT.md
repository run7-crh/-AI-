# Code Health Re-Audit（独立复审）

- 日期：2026-09-27
- 分支：`codex/auth-admin`，HEAD = `22e2e11`
- 审查基线：`464cb53`（阶段 1 只读审查的 HEAD），其后 12 个提交 = Agent 增量改造 7 笔（e20d322…a953919）+ README 重写（db033f2）+ 视觉 A/B/C 四笔（2163621…22e2e11）
- 工作区：干净（仅既有未跟踪 `.zcodeignore`），本次审查未修改任何代码
- 复审者声明：按"第一次接触本项目"执行，**不假设任何此前修改正确**

---

## 审查方法与证据等级

本次复审全部结论基于四类独立证据，**无一项仅凭"读起来像"判定**：

1. **机器验证**：后端 pytest（512 passed / 182s）+ 前端 vitest（125 passed / 26 文件）+ `vue-tsc --noEmit` 通过——我亲自重跑；
2. **运行时探针**：对新服务的失败降级/安全旗标路径直接构造输入执行（如 `_assess_risk`/`_build_advice` 实跑，验证 `high_risk=True`、旗标串与判定元组匹配、保守模板渲染）；
3. **AST 静态扫描**：对 6 个新增/大改模块做未定义名（NameError 级）扫描——全部干净；
4. **三路宽度探查**：死代码/开关/耦合、前端、测试与评估资产，全部带 `文件:行号` 证据。

> 方法论备注（与"特别检查"直接相关）：审查中一度疑似发现 P0 级问题（`ticket_analysis_service.py` 内标识符"拼写不一致"）。经运行时探针 + AST 扫描双重机器验证，**该疑点不成立**（是我自己的判读伪影，文件无恙，旗标串与 startswith 元组精确匹配、运行时行为正确）。此疑点已按证据纪律排除，未写入任何问题清单。这正说明：本报告每一条问题判定都有机器或行号级证据，不依赖单次目测。

---

## 1. Previous Problems（逐项判定）

判定口径：FIXED / PARTIALLY FIXED / NOT FIXED / REGRESSION。

| # | 问题（来源） | 判定 | 证据 |
|---|---|---|---|
| 1 | 管理端 AI Copilot 全缺失（阶段1 §7：UI/API/生成逻辑全空白） | **FIXED** | `TicketAnalysisService`（424 行编排器：聚合→检索→结构化诊断→安全过滤→持久化）+ `POST /api/admin/tickets/{id}/ai-analysis`（admin-only，401/403/404/422/503/504 映射完整）+ `AdminTicketDetail.vue` AI 面板（采用=仅预填回复框，发送仍是人工）；lifespan 装配（main.py:229-240） |
| 2 | `agent_suggestion` 死映射（后端从不写入，前端文案永不出现） | **FIXED** | 写入：ticket_analysis_service.py:415-419（`append_event(event_type="agent_suggestion", actor_type="agent")`）；用户侧过滤 api/tickets.py:29,133-135（`_INTERNAL_EVENT_TYPES`）；管理端全量可见；前端渲染 + 9 个组件测试 |
| 3 | Agent 无建单能力（`actor_type="agent"` 分支从未被调用） | **FIXED** | chat.py:416-443 胶水：`auto_create_ticket=True` 且开关开启时调 `create_draft_from_conversation(actor_type="agent")`；**ticket_service/ticket_store 零改动**（实施承诺经 diff 核实兑现）；只建 draft 不转状态（ticket_service.py:465-466 禁转未放宽）；45 题真实评估 **0 误建单**；失败仅 warning 不阻断 SSE；高风险首轮不自动建单 |
| 4 | 信息充分性判断与主动追问缺失（阶段1 §6 🔴） | **FIXED** | DecomposeSchema +3 字段；`_should_followup` 九条件守卫（nodes.py:352-381，保守默认不追问）；`ask_followup` 节点（失败降级静态追问）；跨轮上限：chat.py:208-215 检测上轮 `route_path=="followup"` 注入 `followup_just_asked` → builder.py:103 门控，最多连续追问 1 轮；24 个专项测试（LLM 全 stub） |
| 5 | 结构化诊断缺失（七段自由文本，无机器可读对象） | **FIXED** | `DiagnosisSchema` 家族 + `diagnose` 节点（仅 local 支路，失败降级 None 不阻断）；**引用程序校验** `_validate_diagnosis_citations`（citations ⊆ 检索证据 id，非法即弃、全无则 confidence 归零——LLM 无法编造证据 id）；真实评估 23/23 引用有效；query_log +2 列（recommended_action/diagnosis_json，PRAGMA 缺列迁移先例） |
| 6 | 无工单决策节点（只有布尔升级） | **FIXED** | `decide_action` 零 LLM 规则阶梯 G0 escalate → G1 followup 透传 → G2 create_ticket（六条件且质量未判失败）→ G3 answer；judge_log 记录触发规则与信号快照；22 个测试，全文件 0 个 LLM patch（节点本身不调 LLM） |
| 7 | 评估脚本缺登录、无人机版从未真实跑通 | **FIXED** | run_eval.py:1012-1030 进程内 ASGI 注册+登录（无真实网络、无密钥泄漏，grep sk-/字面量 key 零命中）；**首份真实基线落盘**：`backend/eval/reports/report_20260926_141228.json`（我亲自验证存在，route_accuracy 0.689 等真实数字） |
| 8 | FastAPI title 残留"学AI必备助手 API" | **FIXED** | a953919 修正 main.py |
| 9 | `tickets.serial_number`/`firmware_version` 幽灵列（无人写入） | **NOT FIXED**（by design） | 列存在、INSERT 恒 None（ticket_store.py:113,126）、无写入方、前端仅类型定义（types/index.ts:278-279）+ 测试夹具。预留字段、文档如实。保留合理：设备档案是新业务面，未授权前不该顺手实现 |
| 10 | `token_usage_json` 预留 + `_infer_models_used` 推断值 | **NOT FIXED**（by design） | chat.py:662 仍写 None；docstring 如实自述"本轮非真实采集，P2 填充"。诚实标注未变，不算伪装 |
| 11 | `has_source` 只认两种前缀、只写不读 | **NOT FIXED** | chat.py:604 原样；本次新增确认：全仓无任何读取方（纯写不读）。影响面为零 |
| 12 | 评估 gold 全 `inferred` 未人工复核 | **NOT FIXED** | 47 题数据集 gold 仍 inferred（实施报告 §18.1 如实声明，README 同口径）。流程债，非代码债 |
| 13 | 多轮追问场景未自动化验证（2 题 skipped_multi_turn） | **NOT FIXED** | 实施报告 §18.2 已知限制，如实记录 |
| 14 | 评估暴露的行为债：answer→escalate 误报 6、service_needed 漏报 4、时效词表误伤"升级固件"、decompose 不认排查史 | **NOT FIXED**（by design） | 实施报告 §19 明确列为后续迭代方向；09-27 功能冻结决策冻结功能开发。已知、已量化（action_accuracy 65.1% 的构成有分析）、已文档化——是"规划中的已知债"，不是"被掩盖的问题" |
| 15 | 延迟压测/并发验证未做；管理端分析同步接口 | **NOT FIXED** | 实施报告 §18.4 已知限制（大工单数秒级，按需触发） |
| 16 | 真实损伤图集缺失（视觉阶段遗留） | **NOT FIXED** | vision 评估用合成夹具 5 张（eval/vision_fixtures/vs01-05.png）+ 真实 VLM 出数；真实损伤照片集未建（功能冻结记录在案） |
| 17 | manifest.json document_count=70 vs 实际 71 | **NOT FIXED**（授权保留） | 既有授权记录维持 |
| 18 | README 未同步改造内容（实施时 §18.5 遗留） | **FIXED**（后置完成） | db033f2 按 18 节模板重写并同步 16 节点拓扑/47 题 v2.1/488+116/首份真实基线/3 开关/ai-analysis 端点 |

**汇总**：FIXED 8（含 1 项后置）、NOT FIXED 10（其中 5 项为"by design 的预留/授权/已知债"，均有文档如实标注）。**REGRESSION：0**。

---

## 2. Newly Introduced Problems（本次重构新产生）

按严重度排列。**未发现任何 P0/P1 级新问题**；以下全部为中低或信息级。

### N1（中）services → graph 私有符号导入
`ticket_analysis_service.py:23-28` 从图层导入三个**下划线私有**符号：
```python
from app.graph.nodes import (_format_evidence_with_ids, _validate_diagnosis_citations, _SAFETY_KEYWORDS)
from app.graph.tools import DecomposeSchema, DiagnosisSchema, call_llm, retrieve
```
依赖**方向**本身正确（服务层→图层 = 高层→底层；图层对 services 零依赖，grep 核实），且 import 期即失败（非静默破坏）、有 docstring 说明、有测试覆盖。但跨文件引用私有名意味着图层内部重构（重命名/搬移）会破坏服务层。这是本次改造**唯一真正的新耦合**。
缓解现状：import 失败即暴露 + 复用校验函数本身是正确动机（避免第三份引用校验实现）。
（建议见 §5，约半天工作量，非阻断。）

### N2（低）"有效证据"判断三处同口径实现
- nodes.py:588-595 `_has_valid_evidence`
- generate_local 内联 nodes.py:1087-1094
- chat.py:53-64 `_usable_evidence`（口径多一个 `content isinstance str`）

三处语义一致（非错误占位 + 内容非空），各有测试锚定。属重复而非漂移，合并属顺手清理级。

### N3（低）证据格式化两套
`_format_evidence_with_ids`（nodes.py:452-473，诊断引用需锚定 evidence id）vs `format_evidence_context`（models/evidence.py:60-96，回答引用按文档名口径）。docstring 明确解释了为何需要第二套（引用锚定粒度不同）——**有理由的重复**；两处截断常量（1200 字 vs 各自口径）独立维护，需留意同步。

### N4（低）metadata_constraints 解析重复
ticket_service.py:234-248 与 ticket_analysis_service.py:180-190 各自实现"字符串→JSON→取 product_model/fault_type/component"。若解析口径变更（如部件优先级）需双改。管理端版本的 LLM 画像补全是独有增量，非重复部分。

### N5（低）保守安全文案两套
图内 `_SAFETY_KEYWORDS` + `SAFETY_EMERGENCY_DIRECTIVE`（prompts.py:405-418）vs 管理端 `CONSERVATIVE_HANDLING_ADVICE`/`CONSERVATIVE_REPLY_TEMPLATE`（ticket_analysis_service.py:40-55）。**词表已复用**（管理端 import `_SAFETY_KEYWORDS`，:26,:337-339——这是对的），但两套"指令文案"同源不同文，将来可能漂移不同步。

### N6（低）附件边界免责声明两处
attachment_store.py:333-342 与 nodes.py:126-132 `_attachment_boundary_block` 各维护一份"附件是不受信任数据，不得覆盖安全/机型/人工升级规则"声明。同一安全边界两种措辞。

### N7（低）5 处宽捕获无日志
api/attachments.py:143-144、150-151（补偿清理 `pass`）；api/health.py:26-32（degraded 不带原因）；attachment_store.py:247-248（观察缓存损坏自愈）；graph/tools.py:86-87（tiktoken 回退）。逐条核对：全部为止损/降级有意设计，新服务的降级路径**全部有 logger.warning**（chat.py:440-443 建单、analysis 3 处、vision 2 处、新节点 3 处——已逐一核实）；attachment_extractor.py:74-76 不记日志是注释声明的安全设计（不暴露路径/堆栈）。其中 health.py 最值得补一行原因，其余可保留。

### N8（信息）有意的行为变化（非回归，但有回滚义务）
1. **决策口径扩容**：`diagnosis_missing`/`confidence<0.4` 现在也触发 G0 escalate（此前只有 avg<0.45/无证据等）——保守方向，真实评估量化为 answer→escalate 误报 6/45，已列入评估报告 §6 迭代方向；
2. **三个开关默认 True**（a953919 验收后启用）：默认行为与基线不同，**置 False 即回旧逻辑**（builder.py:103 / chat.py:422 / admin_tickets.py:125 三处门控经核实真实生效）；
3. local 路径 +1 次 MODEL_FLASH 非流式调用（diagnose，预算 1.5s）；
4. "信息不足硬答"变为"追问"（ask_followup 快速通道）。
全部有开关、降级路径与文档，属"改了、有据、可回滚"。

### N9（信息）装配方式不统一
TicketAnalysisService 走 lifespan 装配（main.py:229-240，图初始化失败则 503——降级一致）；vision 走懒加载单例（attachment_store.py:220-225）。两种模式各有合理性（analysis 依赖图；vision 是可选外呼），但读代码需要知道两套装配路径。

### N10（低）前端重复与死导出（多为存量延续，本次小幅扩大）
- `eventLabels`/`actorLabels`/`eventLabel()` AdminTicketDetail.vue:63-97 与 TicketTimeline.vue:12-40 逐字重复（前者多 agent_suggestion/internal_note 两项）；AdminTicketDetail 自渲染时间线而非复用 TicketTimeline（有理由：需展示内部事件，但标签映射未抽共享）；
- 状态徽章 3-4 种实现（AdminTicketDetail/AdminTicketQueue 直出原文，TicketDetailView/TicketsView 各有映射且文案不一致）；日期格式化 4 种；
- api 层 `ensureOk` 四种模式：tickets.ts/attachments.ts 两份逐字重复、**conversations.ts/feedback.ts 是空操作 ensureOk**（每处调用白跑）、http.ts:41-43 `apiJson` 零调用方死导出；
- `AgentSuggestion`/`AgentAnalysisKnowledge` 类型内联在 api/adminTickets.ts:52-88 而非 types/index.ts（本次新增代码跟随了既有内联模式）；AdminTicketDetail.vue:57 一处 `as unknown as AgentSuggestion` 双重断言（非测试源码零 `any`，总体类型纪律好）。

### N11（低）测试缺口（新功能边界）
- 前端：`runAnalysis` 失败路径（analysisError 展示）无用例；InputBox 不支持类型拒绝分支无用例；
- 后端：`route_after_combined_quality` 现挂载在 decide_action 出边，**无函数级路由测试**（拓扑变化由 e2e 图测试间接覆盖：test_builder.py:164 端到端 pass 路径、:311 幻觉→quality_fail 路径）；无独立 `route_after_decide_action` 测试（因复用原函数，风险低）。
其余覆盖良好：新节点 LLM 全 stub、守卫矩阵 11+ 场景、无 sleep/真实网络、仅 1 处 importorskip、无 skip/xfail；AI 面板"采用=仅预填不自动发送"有显式断言（AdminTicketDetail.test.ts:193）。

### N12（信息）文件体积
nodes.py 1434 行（13→16 节点）——分节注释清晰、每节点独立函数、无跨域职责混杂，**未构成 God Object**，但已是大文件；chat.ts store 645 行；AdminTicketDetail.vue 421 行。属于"大而清晰"，继续加节点前建议按职责分模块。

---

## 3. Architecture Comparison（Before vs After）

| 维度 | Before（464cb53） | After（22e2e11） |
|---|---|---|
| 图拓扑 | 13 节点 + 5 路由，CRAG 回路 | 16 节点 + 5 路由（+ask_followup / diagnose[仅 local 支路] / decide_action） |
| Agent↔业务 | 单向、图外、快照式；图对工单零访问 | 图后胶水自动建草稿（复用 TicketService，**ticket_service/store 零改动**）+ 管理端 AI Copilot（复用生产检索器，无第二套检索） |
| 诊断 | 七段自由文本 | 结构化 DiagnosisSchema + 引用程序校验（非法 id 即弃/置信归零）+ query_log 持久化 |
| 决策 | escalation_required 布尔 | 四值确定性阶梯 answer/followup/create_ticket/escalate（零 LLM，judge_log 记录触发规则） |
| 信息不足 | 硬答 | 九条件守卫 + ask_followup 快速通道 + 跨轮上限 1 |
| 评估 | 脚本从未真实跑通 | 进程内登录 + 47 题真实基线落盘 |
| 视觉 | 无 | 图片附件 VLM 结构化观察（默认关；观察≠证据红线：观察不进 citations、信封式边界声明） |
| 测试 | 409 + 99 | **512 + 125 全绿**（本次亲自重跑）+ vue-tsc 通过 |
| 依赖方向 | graph 不依赖 services | 不变（graph 仍零依赖 services）；新增 services→graph（含私有符号，见 N1）；main↔chat 受控循环为既有 |
| 开关 | — | 5 个布尔开关全部有读取点、无死开关；Agent 三开关验收后默认 True、置 False 回滚 |

**结论**：所有变化均为增量（加节点/加字段/加端点/加开关），CRAG 回路、SSE 协议、工单状态机、认证、附件安全、知识库均零重写；`app/rag/*`、`fault_progress_service.py`、`auth_store.py` 零改动经 diff 核实。架构演化方向与 target_architecture.md 设计一致。

---

## 4. Remaining Technical Debt（只列真正值得处理的）

### 值得处理（按优先级）
1. **N1 私有符号跨层导入**：把 `_format_evidence_with_ids`/`_validate_diagnosis_citations`/`_SAFETY_KEYWORDS` 提升为图层公共 API（如 evidence 专用模块）——约半天，是唯一影响长期演化速度的耦合。
2. **两个小测试补齐**：`route_after_combined_quality` 挂载点后移后的函数级路由断言（后端 1 个用例）；`runAnalysis` 失败路径（前端 1 个用例）。合计 1-2 小时。
3. **评估 §6 决策口径修正**（功能解冻后第一项，预计 action_accuracy +10pt）：非排查意图跳过 diagnosis_missing 触发的 escalate、decompose 把"已排查 N 次"当充分信号、时效词表拆分。改 `decide_action_node`/`_decide_low_confidence` 时同步 test_decide_action。
4. **health.py degraded 无原因**（一行日志）。

### 可保留、不值得专项处理（明确建议不动）
- 幽灵字段 serial_number/firmware_version/token_usage_json（预留 + 诚实文档化，删除反而破坏 schema 兼容）；
- has_source 只写不读（影响面零）；
- manifest 70 vs 71（授权保留）；
- N2-N6 重复（下次触碰对应文件时顺手合并即可，不值得专项重构——重复本身有测试锚定、无漂移）；
- N7 其余无日志的止损 except（有意设计）；
- N9 装配双模式、N10 前端存量微尘（空操作 ensureOk/apiJson 死导出等，顺手清理级）；
- nodes.py 1434 行（结构清晰，下次加节点时分模块）；
- gold 人工复核、多轮场景自动化、延迟压测、真实损伤图集——流程/资产债，随真实用户与解冻阶段解决，非代码问题。

---

## 5. Final Recommendation

### 当前是否适合继续开发：**适合，且应停止重构**

核心判据（全部为本次实测）：
1. **512 后端 + 125 前端全绿**，类型检查通过；新旧能力测试密度均良好（新节点全 stub、无网络依赖、仅 1 处 importorskip）；
2. 16 节点拓扑与代码、文档、README 三方一致（我逐边核对 builder.py）；
3. **"为修一个问题制造另一个问题"的检查结论：未发现**。最接近的候选（N1 私有符号导入）有 import 期失败保护 + 测试覆盖 + docstring 说明；审查中唯一疑似 P0（标识符损坏）经运行时探针 + AST 扫描双重机器验证排除，为假阳性；
4. 新增能力全部具备：配置开关 + 失败降级（有日志）+ 回滚语义 + 测试；安全红线未放宽（agent/system 禁转状态、高风险永不追问/不自动建单、synthetic 不作确诊依据、AI 不自动发送——均有负例测试且绿）；
5. 遗留问题要么是"有授权/有文档的预留"（10 项 NOT FIXED 中 5 项 by design），要么是低影响微尘。**继续无限重构没有收益。**

### 必须解决（继续开发前，合计约 1 天）
- N1：私有符号提升为公共 API（半天）；
- N11：两个小测试补齐（1-2 小时）；
- health.py 补一行降级原因（5 分钟）。

### 可以暂时保留
- N2-N10 全部（低优先级，触碰对应文件时顺手处理）；
- 全部 by-design 预留（幽灵字段/manifest 差异/token_usage）；
- 功能冻结决策维持——唯一值得做的功能项是"售后报告生成"（既有结论），以及解冻后第一优先的决策口径修正（N8.1，评估 §6）。

### 后续开发最需要遵守的工程规则
1. **依赖方向**：graph 不得 import services（已守住，保持）；跨层复用一律走公共 API，**禁止下划线私有符号跨文件引用**（N1 的教训）；
2. **开关纪律**：新能力必须带配置开关 + 失败降级（降级路径必须有 logger）+ 回滚语义——延续现有三开关模式；
3. **行为变化必过评估集**：真实基线已在（report_20260926_141228.json），任何决策口径/提示词改动先跑分再合入，评估需隔离库（自动建单会写库）；
4. **安全文案单一来源**：新增安全相关文案先复用 `_SAFETY_KEYWORDS` 与既有指令，不另起第二套词表/模板；
5. **重复的处置节奏**：发现重复先判断"有理由的重复"（口径不同，如两套证据格式化）还是漂移风险（如同源安全文案），前者保留并注释、后者合并——不为消重复而消重复；
6. **诚实边界**：预留字段/推断值/未复核 gold 必须在 docstring 与文档中如实标注（现有纪律良好，保持）；
7. **大文件节奏**：nodes.py 等继续增长前先分模块，避免下一个 God Object。

---

*本报告基于 2026-09-27 工作区实测（测试重跑 + 运行时探针 + AST 扫描 + 三路宽度探查），所有问题判定附 `文件:行号` 级证据；审查过程零代码修改。*
