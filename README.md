# 无人机智能售后技术支持 Agent

`Python 3.11+` · `FastAPI` · `LangGraph` · `Corrective RAG` · `Chroma` · `DeepSeek` · `Vue 3`

一个面向无人机售后场景的 Agentic Workflow / Corrective RAG 系统。基于 `data/drone` 中的结构化知识库，回答产品参数、型号识别、故障排查、SOP 操作、校准保养、飞行安全、合规法规和模拟案例参考问题；高风险场景（电池、失控、坠落、进水等）先执行安全判断与人工升级，全程来源可溯。

> 定位说明：本项目的核心是**固定拓扑的 Agentic Workflow + Corrective RAG + 确定性业务决策**（LLM 供给信号，行动由规则阶梯裁决），不宣称具备模型自主工具选择的 ReAct 或完整 Self-RAG 能力。

## 目录

1. [项目简介](#1-项目简介)
2. [项目背景 / 问题定义](#2-项目背景--问题定义)
3. [核心功能](#3-核心功能)
4. [系统架构](#4-系统架构)
5. [技术栈](#5-技术栈)
6. [核心技术实现](#6-核心技术实现)
7. [数据与知识库](#7-数据与知识库)
8. [项目目录](#8-项目目录)
9. [快速开始](#9-快速开始)
10. [配置说明](#10-配置说明)
11. [API / 接口说明](#11-api--接口说明)
12. [测试与评估](#12-测试与评估)
13. [项目效果 / 指标](#13-项目效果--指标)
14. [Demo / 截图](#14-demo--截图)
15. [项目难点与解决方案](#15-项目难点与解决方案)
16. [项目复盘](#16-项目复盘)
17. [后续规划](#17-后续规划)
18. [License](#18-license)

---

## 1. 项目简介

无人机售后咨询的特点是：问题横跨参数、故障、操作、安全、法规多个文档类型，答错代价高（错误操作可能造成炸机或人身伤害），且用户往往说不清机型。本项目用 LangGraph 构建固定拓扑的 Agent 工作流，把"意图识别 → 安全判断 → 检索 → 纠错重试 → 质量检查 → 业务决策"组织成可观测的流水线：

- **检索增强而非裸生成**：答案基于本地知识库（Chroma 向量检索 + bge-reranker 重排），来源卡片逐条可溯。
- **元数据感知**：意图路由产出机型/部件/故障类型约束与文档类型优先级，用户未确认机型时不强行套用，约束无命中时自动扩大范围，但绝不把其他机型的参数当作当前机型的答案（跨机型污染防护）。
- **安全优先**：高风险场景拼接紧急处置指令，低置信或用户要求时升级人工，高风险工单禁止系统自动关闭。
- **业务决策阶梯**：信息不足先主动追问（最多连续 1 轮），排查类问题产出结构化诊断（引用程序校验），再由零 LLM 规则阶梯决定回答 / 追问 / 建单 / 升级人工；Agent 建单复用工单系统且只建草稿，提交始终是用户动作。
- **可评估闭环**：47 题（v2.1）真实在线评估集 + 覆盖路由/检索/生成/安全/业务决策的多维指标，`query_log` 全量落库支撑回归。

系统同时包含完整的业务侧能力：账号与权限、附件上传解析、售后工单闭环（含 Agent 自动建单草稿与管理端 AI 售后 Copilot）、管理台（用户管理 / 反馈统计 / 日志 / 知识库导入 / 索引重建）和知识图谱可视化。

## 2. 项目背景 / 问题定义

| 现实问题 | 表现 | 本项目的应对 |
| --- | --- | --- |
| LLM 幻觉 | 编造不存在的参数、固件版本、操作步骤 | RAG 强制引用证据 + 质量检查节点（幻觉判定不通过则降级为质量警告） |
| 跨机型污染 | 把 A 机型的电池参数回答给 B 机型的用户 | frontmatter 元数据硬过滤 + 明确机型时严格排除其他机型文档 + 评估集专设 `cross_model_trap` 类别 |
| 高风险场景 | 电池鼓包 / 飞行中失控 / 进水，通用模型直接给维修步骤 | 安全判断节点分级（`high/none` × 场景），高风险拼接紧急处置指令（如飞行中只给返航/降落指引），必要时升级人工 |
| 排查失败无人接手 | 用户按步骤操作多次仍无效，机器人反复循环 | 故障进度跟踪：同一故障确认"试过且无效"达 2 次自动升级人工，聊天页可一键生成售后工单 |
| 信息不足硬答 | 用户描述模糊（"飞机总往一边偏"）时模型直接编造排查步骤 | 信息充分性检查 + 主动追问（守卫矩阵、最多连续 1 轮、高风险永不追问） |
| 知识散落、不可溯源 | 客服依赖个人经验，答案无法核对 | 知识库 Markdown 化 + frontmatter 结构化，答案附来源卡片（文档/机型/部件/数据性质/分数） |

## 3. 核心功能

**智能问答**
- SSE 流式输出（token 级）、停止生成、重新生成、多会话管理
- 意图路由（10 类意图）→ 按意图加权文档类型；多步问题自动分解（最多 5 个子问题）；闲聊分流
- 信息不足主动追问：充分性检查识别缺口后前置安全提醒、逐条解释为什么问；同一会话最多连续追问 1 轮，第二轮必须尽力作答
- TraceTimeline 思考过程可视化：流式期间逐节点点亮，可展开查看每个节点的思维链与中间产物（改写后的问题、重排均分等）

**安全与可靠性**
- 高风险安全判断（`safety_level` / `safety_situation`）+ 紧急处置指令 + 历史安全提示
- 人工升级判定：用户要求 / 同一故障排查失败 ≥ 2 次 / 高风险 / 低置信（重排均分 < 0.45）
- 质量检查节点：幻觉 + 回答质量合并判定，不通过则附质量警告而不冒充可信答案

**Agent 售后闭环**
- 结构化诊断：可能原因 / 处理步骤 / 安全警示 / 置信度，引用逐条锚定到真实检索证据（程序校验，LLM 无法编造证据 id）
- 确定性决策阶梯：escalate → followup → create_ticket → answer 由零 LLM 规则裁决，触发规则与信号快照写入 judge_log 可追溯
- Agent 自动建单：决策命中建单条件时自动创建工单草稿（复用工单服务、每会话幂等、高风险首轮不建单），前端横幅提示，提交仍是用户动作
- 管理端 AI Copilot：聚合工单 / 事件 / 证据 / 会话 / query_log 并复用生产检索器，产出诊断 + 处理建议 + 回复草稿 + 风险旗标；采用建议仅预填回复框，发送仍是人工动作

**来源与知识**
- 来源卡片：文档类型、来源类型（本地知识库 / 联网资料 / 用户附件）、机型、部件、故障类型、数据性质、分数
- `synthetic` 模拟案例明确标注，不得作为确诊依据
- 知识图谱页（ECharts 力导向图）：点击节点查看关联概念，支持"一键提问"

**附件与工单**
- 附件上传与解析（pdf / txt / md / docx / log / json / csv），内容进入回答上下文
- 售后工单闭环：聊天页一键生成工单草稿（机型 / 故障分类 / 安全等级由服务端从会话快照判定，前端不可覆盖）→ 用户编辑标题与描述后提交 → 管理员接单 / 转派 / 请求补充 / 公开回复 / 内部备注 → 用户补充信息、确认解决或重开

**账号与运营**
- 用户名密码注册登录（scrypt 哈希 + HttpOnly Cookie 服务端会话）、admin 角色与后端强制鉴权
- 管理台：用户管理、反馈统计（点赞点踩 + 无帮助原因）、系统日志、Markdown 知识库导入与索引重建

## 4. 系统架构

```text
浏览器（Vue 3 + Pinia + ECharts，http://localhost:5173）
   │  REST + SSE（/api/*，Vite 开发代理 → :8000）
   ▼
FastAPI 应用层 ── Cookie 会话鉴权 / slowapi 限流 / 统一错误处理 / SSE 编排
   │
   ├─ LangGraph Agent 工作流（16 节点，5 条路径：闲聊 / 追问 / 本地 RAG / 联网 / 多步分解）
   │     ├─ 意图与元数据约束抽取 → metadata_constraints / document_type_priority
   │     ├─ 安全判断 → safety_level / escalation_required
   │     ├─ Corrective RAG 回路（rag_retrieve ⇄ query_corrector，最多重试 1 次）
   │     └─ 确定性业务决策（decide_action）→ 自动建单草稿 / 升级人工（能力开关可回退）
   │
   ├─ RAG 管线（LlamaIndex + Chroma）
   │     ├─ Embedding：BAAI/bge-large-zh-v1.5（1024 维，本地 HuggingFace）
   │     ├─ Reranker：BAAI/bge-reranker-v2-m3（CrossEncoder，GPU 优先，启动预热）
   │     └─ 向量库：Chroma 持久化 collection「drone_kb」（版本化原子重建）
   │
   ├─ 服务层（SQLite WAL，12 张表）
   │     会话/消息 · query_log · 反馈 · 用户/会话令牌 · 工单/审计事件/工单证据 · 附件 · 故障进度
   │
   └─ 外部服务：DeepSeek（deepseek-chat / deepseek-reasoner）、Tavily（联网兜底检索）
```

## 5. 技术栈

| 层 | 技术 |
| --- | --- |
| 后端框架 | Python 3.11+、FastAPI、Uvicorn、sse-starlette（SSE）、Pydantic Settings、slowapi（限流）、tenacity（重试） |
| Agent 编排 | LangGraph（StateGraph，16 节点）、langchain-openai（DeepSeek OpenAI 兼容接口）、tiktoken（历史截断） |
| RAG / 检索 | LlamaIndex 0.10+、Chroma、sentence-transformers（CrossEncoder 重排）、torch、python-frontmatter、pypdf |
| 模型 | Embedding：`BAAI/bge-large-zh-v1.5`；Reranker：`BAAI/bge-reranker-v2-m3`；生成：`deepseek-chat` / `deepseek-reasoner`（多步推理） |
| 联网检索 | Tavily（相关性不足 / 纠错重试失败 / 时效性问题兜底） |
| 存储 | SQLite（aiosqlite，WAL 模式，12 张表）、Chroma 持久化、本地文件（附件 payload） |
| 前端 | Vue 3 + TypeScript、Pinia、Vue Router、Tailwind CSS、ECharts（知识图谱）、markdown-it + highlight.js、Vite、Vitest |
| 测试 | pytest + pytest-asyncio（后端）、Vitest + @vue/test-utils + jsdom（前端） |

## 6. 核心技术实现

### 6.1 Agent 工作流

LangGraph 图定义在 `backend/app/graph/builder.py`，共 **16 个节点**（★ 为 Agent 售后升级新增）：

```text
rewrite_query（指代消解改写）
  └─▶ decompose_question（意图 / 元数据约束 / 安全判断 / 信息充分性与缺口 / 是否多步）
        ├─ 闲聊且无设备风险 ─────────────────▶ chitchat_node ─▶ END
        ├─ 信息不足且守卫通过 ─▶ ask_followup（主动追问，不检索不质检）★ ─▶ END
        ├─ 多步问题 ─▶ multi_step_reason（逐子问题 RAG，低分子问题 Tavily 兜底）─┐
        └─ 单步问题（高风险自动覆盖闲聊与追问通道）─▶ judge_relevance            │
                 ├─ 相关 ─▶ rag_retrieve ─▶ rag_quality_eval                  │
                 │               ├─ 通过 ─▶ diagnose ★ ─▶ generate_local ─────┤
                 │               ├─ 不通过（未纠正）─▶ query_corrector ─▶ rag_retrieve（CRAG 回路，≤1 次）
                 │               └─ 不通过（已纠正）─▶ web_search ─▶ generate_online ─┤
                 └─ 不相关 ─▶ web_search ─▶ generate_online ───────────────────────────┤
                                                                                       ▼
                                          combined_quality_check（幻觉 + 质量，一次判定）
                                                                   │
                                          decide_action（零 LLM 确定性规则）★
                                            ├─ 质量通过 ─▶ END
                                            └─ 失败 ─▶ quality_fail（附质量警告）─▶ END

  图运行后（chat.py 胶水，非图节点）：auto_create_ticket → 复用 TicketService 建工单草稿（actor=agent）
```

- **状态设计**（`app/graph/state.py`）：`AgentState` 分六组字段——输入（query / history / attachment_*）、路由中间产物（intent / metadata_constraints / document_type_priority / is_relevant）、质量（has_hallucination / answer_quality_pass）、安全（safety_flag / safety_level / safety_situation / escalation_required）、业务决策（recommended_action / diagnosis / auto_create_ticket / followup_just_asked / information_gaps，全部 Optional）、输出（final_answer / route_path / quality_warning）。判断日志 `judge_log` 用 `operator.add` reducer 追加。
- **意图与元数据策略**（`app/graph/intent.py`）：10 类意图各自映射文档类型优先级（如 `troubleshooting → [troubleshooting, sop, case]`），`MODEL_ALIASES / COMPONENT_TERMS / FAULT_TERMS` 从文本抽取机型/部件/故障约束。
- **多步推理**使用 `deepseek-reasoner`，子问题去重后逐个检索，思维链以 `reasoning` 事件流式返回前端。
- **主动追问**（`ask_followup`，★）：`DecomposeSchema` 一次输出 `information_sufficient / information_gaps / symptoms`；通过九条件守卫矩阵（意图 ∈ troubleshooting / flight_safety、非高风险、未连续追问、无附件、未要求人工、未排查失败、非多步）才进入追问。追问流式生成（安全提醒前置 + 逐条解释为什么问），失败降级静态追问；追问轮不检索、不进质量检查。跨轮由 chat.py 检查上一轮 `route_path=="followup"` 注入 `followup_just_asked`，保证最多连续追问 1 轮。
- **结构化诊断**（`diagnose`，★）：仅 local 支路，在检索质量通过后、生成前运行（MODEL_FLASH，预算 ≤1.5s）。`DiagnosisSchema` 含可能原因三分标注 / 处理步骤四要素 / 带 `data_type` 的引用；**citations 程序校验 ⊆ 检索证据 id**，非法引用即弃、全部无效则置信度归零。诊断以"校对块"注入生成上下文，失败降级 None 不阻塞回答。
- **确定性业务决策**（`decide_action`，★）：所有生成路径必经，**零 LLM**——G0 escalate（要求人工 ∨ 排查失败 ∨ 高风险 ∨ 低置信）→ G1 followup 透传 → G2 create_ticket（充分 ∧ 排查意图 ∧ local ∧ 需人工服务 ∧ 置信度 ≥ 0.55 ∧ 质量未判失败）→ G3 answer。LLM 只供给信号，行动由规则裁决；触发规则与信号快照写入 judge_log，可进 TraceTimeline 与评估。

### 6.2 RAG（Corrective RAG）

- **相关性判断三级短路**：top1 重排分 ≥ 0.5 直接判相关；top3 均分 ≥ 0.4 短路通过；灰区才调 LLM 复核——本地重排 < 100ms vs LLM 1–3s，显著降低 token 成本与延迟。
- **Corrective RAG 回路**：检索质量评估不通过时，`query_corrector` 依据失败原因二次改写查询重试；**最多重试 1 次**，仍失败转联网兜底（平衡"浪费本地知识库"与"死循环风险"）。
- **联网兜底触发时机**：① 相关性判断为不相关；② 纠错重试后仍不通过；③ 多步推理中某子问题本地最高分 < 0.3。Tavily 返回统一 Evidence 结构（`web:<sha256前16>`），失败时返回错误占位条目并置 `quality_warning`，不中断流程。
- **质量检查合并**：幻觉判定与回答质量评估合并为一次 LLM 调用（`combined_quality_check`），调用次数 6 → 5，端到端延迟降 1–2s；不通过时 `quality_fail` 只附质量警告，不覆盖已生成答案。

### 6.3 知识库

- **Profile 机制**：`KB_PROFILE=drone`（默认）使用 `data/drone` + collection `drone_kb`；`KB_PROFILE=obsidian` 兼容旧 AI 学习库（`data/raw` + `obsidian_kb`）。
- **文档读取器**（`app/rag/readers.py`）：`DroneMarkdownReader` 把 frontmatter 身份字段（document_type / product_model / component / fault_type / data_type / source_type 等）提升进向量 metadata；剥离 wikilink/callout，sha256 生成稳定文档 id；与 `manifest.json` 对账。
- **版本化索引**：重建时写入候选 collection `<name>__v_<uuid>`，成功后原子替换活动指针（`<collection>.active.json`），记录 embedding 模型 / chunk 参数；指纹不一致自动触发 rebuild，支持回滚切换。
- **知识图谱**：`app/rag/graph_builder.py` 规则（wikilink）+ LLM 混合抽取实体关系，输出 `kg.json`，构建失败不阻塞索引。

### 6.4 检索 / Reranker

- **分块**：`SentenceSplitter`，chunk 512 / overlap 50，稳定分块 id `<document_id>:chunk:<n>`。
- **召回**：`VectorIndexRetriever` 先取 `top_k×3`（有元数据约束时 `max(3k, 30)`），再由 CrossEncoder 重排取 top_k=3。
- **元数据感知过滤**：机型为硬约束——用户明确机型时严格排除其他机型文档，无命中时回退通用文档（`product_model ∈ ("", "all")`）；部件/故障类型为软约束。
- **分数融合排序**：排序键 =（文档类型优先级序，-(重排分 + 位次加成)），位次加成 `max(0, 0.12 − rank×0.04)`——意图加权最多提升 0.12 分，不会压过强证据。
- **工程细节**：Reranker 模块级缓存（约 2GB）+ 全局锁串行推理，lifespan 启动预热；同步检索用 `asyncio.to_thread` 包装避免阻塞事件循环。

### 6.5 工具调用

本项目**没有** ReAct 式模型自主工具选择，外部能力以"固定拓扑注入"方式接入：

- **Tavily 联网搜索**：作为独立节点 `web_search` 在确定性时机调用（见 6.2），`max_results=5`，结果转 Evidence 统一格式。
- **检索器注入**：`rag_retriever` 通过 `functools.partial` 注入需要的节点，检索同步调用走线程池。
- **结构化输出**：DeepSeek 不支持 JSON mode，改用 `llm.with_structured_output(schema, method="function_calling")` 实现意图分解与信息充分性（`DecomposeSchema`）、结构化诊断（`DiagnosisSchema` 家族）、质量判定（`CombinedQualitySchema`）、管理端分析（`AdminAnalysisSchema`）的结构化约束。
- **确定性决策节点**：`decide_action` 不调用 LLM——LLM 只供给信号（意图、诊断置信、信息充分性、安全分级），行动由 G0–G3 规则阶梯裁决并写 judge_log，业务行为可解释、可回放。

### 6.6 多轮对话

- **SSE 协议**（`POST /api/chat`）：事件类型 `stage`（节点中文提示）/ `token` / `reasoning`（思维链增量）/ `node_end`（含耗时与白名单输出）/ `attachment` / `final`（最终答案对账，防重复）/ `meta`（路由、来源、judge_log、安全字段、query_log_id，及可选 `recommended_action` / `information_gaps` / `diagnosis` / `agent_ticket`——旧前端忽略未知字段，协议向后兼容）/ `error` / `done`。图执行基于 `astream_events(version="v2")`。
- **会话与历史**：SQLite `conversations/messages` 按用户隔离；历史取最近 10 条，用 tiktoken `cl100k_base` 从最新向前截断至 6000 token。
- **状态持久化**：assistant 消息落库时保存安全/意图/路由/来源/judge_log 等字段，会话详情原样返回；`query_log` 27 列全量记录（原始与改写问题、路由、检索命中、重排均分、最终答案、是否含引用、模型、耗时、错误），支撑离线评估与真实问题回流。
- **停止生成**：客户端中断 SSE 触发 `CancelledError`，`finally` 块用 `asyncio.shield` 保证 query_log 不丢；前端 AbortController 区分"主动停止"（保留已生成内容）与"网络错误"；每条流绑定 `activeRequestId` 防止旧流事件污染新请求；60s 无数据主动止损。
- **流式调用不重试**：只执行一次，避免重复 token，由 `final` 事件对账兜底。

### 6.7 可靠性机制

| 机制 | 实现 |
| --- | --- |
| 安全分级 | `safety_level ∈ {high, none}` × `safety_situation ∈ {in_flight, landed, charging, unknown}`；LLM 输出清洗 + 中英文关键词保守兜底；高风险拼接 `SAFETY_EMERGENCY_DIRECTIVE`（如飞行中只给返航/降落指引、禁止空中断电） |
| 人工升级 | 用户要求人工 ∨ 同一会话同一故障"试过且无效"≥ 2 次（`fault_progress`）∨ 高风险 ∨ 低置信（均分 < 0.45 或无有效证据）→ 拼接 `HUMAN_ESCALATION_DIRECTIVE`，只建议联系官方售后，禁止声称"已转人工" |
| 质量检查 | 幻觉 + 质量一次 LLM 判定（temperature 0.2）；评估调用失败降级为警告不阻塞回答 |
| 限流 | slowapi：`/api/chat` 10/min，`/api/index/rebuild` 1/min，可配开关 |
| 重试 | LLM 非流式调用 tenacity 3 次指数退避（1–8s）；SQLite OperationalError 重试 3 次 |
| 错误处理 | 统一错误映射（认证/限流/超时/Chroma/Embedding/Reranker/Tavily 等）+ 全局 handler |
| 引用格式 | `【来源：文件名】` + Evidence 17 字段（来源类型/机型/部件/故障类型/数据性质/分数…），前端渲染为来源卡片 |
| 日志 | RotatingFileHandler 10MB × 5 份；密钥不入库不入日志 |
| 工单一致性 | 状态转换白名单集中在服务层（API 不可绕过）+ `WHERE status=from_status` 乐观锁 + 同事务写审计事件 |
| 追问红线 | 高风险永不追问（安全覆盖追问分支）；九条件守卫矩阵（意图 / 附件 / 连续追问 / 要求人工 / 排查失败 / 多步）；同一会话最多连续追问 1 轮 |
| 诊断引用校验 | 诊断 citations 程序校验 ⊆ 检索证据 id：非法即弃、全部无效则置信度归零（LLM 无法编造证据引用） |
| Agent 建单红线 | 高风险首轮不自动建单；只建 draft，一切状态转换仍仅限人工；每会话幂等；失败仅告警不阻断 SSE |
| Copilot 安全 | 高风险工单强制保守清单/模板覆盖危险维修建议；`agent_suggestion` 事件用户侧不可见；AI 永不自动发送回复或关闭工单 |

## 7. 数据与知识库

知识库位于 `data/drone`（71 篇 Markdown，全部由 `manifest.json` 登记身份），按文档类型组织：

| 目录 | 数量 | 内容 |
| --- | --- | --- |
| `products/` | 4 | 机型资料：Agras T50、Matrice 350 RTK、Mavic 3 Enterprise、Mini 4 Pro |
| `troubleshooting/` | 13 | 故障排查手册（GPS 异常、充电异常、RTK 信号、图传黑屏等） |
| `sop/` | 10 | 标准操作流程（电池检查、罗盘校准、IMU 校准等） |
| `technical/` | 12 | 技术原理（罗盘、固件、云台相机、GNSS 定位等） |
| `safety/` | 6 | 飞行安全、电池安全、CAAC 合规、异常飞行处置 |
| `cases/` | 26 | 模拟售后案例（CASE-S001~S026，`data_type=synthetic`，标注为参考不可作确诊依据） |
| `sources/` | 1 | 来源登记表（SOURCE-xxx），每篇文档通过 `source_id` 关联出处 |

每篇文档的 frontmatter 携带 8 个身份字段：`document_id`、`document_type`、`product_model`、`component`、`fault_type`、`source_type`（official/synthetic）、`data_type`（factual/synthetic）、`source_id`。检索时这些字段直接参与硬过滤与排序加权。

> 已知差异：`manifest.json` 登记 `document_count=70`，实际 71 篇，该差异按授权记录在案、暂不修改。

旧 AI 学习库（`data/raw`，20 篇 RAG/Agent 学习笔记）通过 `KB_PROFILE=obsidian` 保持兼容。

## 8. 项目目录

```text
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口：lifespan 初始化建库/预热 Reranker/加载索引/构图
│   │   ├── config.py          # Pydantic Settings 全部配置项
│   │   ├── api/               # 路由层：chat / auth / conversations / attachments / tickets
│   │   │                      #        admin_tickets / feedback / admin / index / graph / health
│   │   ├── graph/             # LangGraph：builder / nodes / state / tools / prompts / intent
│   │   ├── rag/               # indexer / retriever / reranker / readers / embedding / graph_builder
│   │   ├── services/          # 会话、query_log、反馈、认证、工单、附件、故障进度
│   │   ├── models/            # Evidence、附件等数据模型
│   │   └── extensions.py      # slowapi 限流器
│   ├── eval/                  # build_dataset.py / run_eval.py / dataset.json（47 题，v2.1）/ reports/
│   ├── tests/                 # unit（345 例）/ integration（60 例）/ e2e
│   └── data/                  # agent.db、chroma、logs、模型缓存（gitignore，不入库）
├── frontend/
│   └── src/
│       ├── api/               # SSE streamChat 手写解析 + REST 封装
│       ├── stores/            # Pinia：auth / chat（最大，含流式状态机）/ tickets
│       ├── views/             # ChatView / LoginView / TicketsView / GraphView / AdminView
│       ├── components/        # TraceTimeline / SourceCard / TicketDraftModal / AdminTicketQueue ...
│       └── router/            # 7 条路由 + 登录/admin 守卫
├── data/
│   ├── drone/                 # 无人机售后知识库（71 篇 + manifest.json）
│   └── raw/                   # 旧 AI 学习库（KB_PROFILE=obsidian 兼容）
├── docs/                      # 知识库工程报告、各阶段设计文档与实施计划
└── RECAP.md                   # 历史复盘记录（v1.1 自测优化、阶段 5 收口）
```

## 9. 快速开始

**环境要求**：Python ≥ 3.11、Node ≥ 18；Reranker/Embedding 本地运行（GPU 可选，CPU 较慢）；首次启动需下载约 2GB 模型缓存并构建向量索引。

**后端**：

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e .
copy .env.example .env        # Linux/macOS 使用 cp
# 编辑 .env：填写 DEEPSEEK_API_KEY、TAVILY_API_KEY 和 AUTH_ADMIN_PASSWORD
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

首次启动会初始化 SQLite（WAL + 迁移）、预热 Reranker、加载或构建版本化 Chroma 索引，并以 `.env` 中的 `AUTH_ADMIN_USERNAME / AUTH_ADMIN_PASSWORD` 创建管理员账号；未设置管理员密码时拒绝启动。

**前端**：

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173，/api 已代理到 :8000
```

**验证**：浏览器打开 http://localhost:5173 用管理员账号登录；接口健康检查 `GET http://localhost:8000/api/health`；API 文档 http://localhost:8000/docs。

## 10. 配置说明

全部配置在 `backend/.env`（从 `.env.example` 复制），完整项见 `backend/app/config.py`。常用项：

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | ✅ | — | DeepSeek API 密钥 |
| `TAVILY_API_KEY` | ✅ | — | Tavily 联网搜索密钥 |
| `AUTH_ADMIN_USERNAME` | — | `admin` | 初始管理员用户名 |
| `AUTH_ADMIN_PASSWORD` | ✅ | — | 初始管理员密码；生产必须改且不可为空 |
| `AUTH_COOKIE_SECURE` | — | `false` | 生产环境（HTTPS）必须设 `true` |
| `AUTH_SESSION_TTL_SECONDS` | — | `604800` | 会话有效期（7 天） |
| `KB_PROFILE` | — | `drone` | 知识库 profile：`drone` / `obsidian` |
| `KB_DATA_DIR` | — | 随 profile | 旧变量，显式设置时优先（兼容规则） |
| `CHROMA_PERSIST_DIR` | — | `backend/data/chroma` | 向量库持久化目录 |
| `CHROMA_COLLECTION_NAME` | — | 随 profile | `drone_kb` / `obsidian_kb` |
| `SQLITE_PATH` | — | `backend/data/agent.db` | SQLite 路径 |
| `EMBEDDING_MODEL` | — | `BAAI/bge-large-zh-v1.5` | Embedding 模型（1024 维） |
| `RERANKER_MODEL` | — | `BAAI/bge-reranker-v2-m3` | 重排模型 |
| `MODEL_PRO_CHAT` / `MODEL_PRO_REASON` | — | `deepseek-chat` / `deepseek-reasoner` | 生成与多步推理模型 |
| `CORS_ORIGINS` | — | `localhost:5173,4173` | 生产需改为实际域名 |
| `ATTACHMENT_TTL_HOURS` | — | `24` | 附件保留期（提升为工单证据后延至 30 天） |
| `KB_IMPORT_MAX_FILE_BYTES` / `_FILES` | — | 10MB / 20 | 管理台知识库导入限额 |
| `SLOWAPI_ENABLED` | — | `true` | 限流开关（测试中自动关闭） |
| `AGENT_FOLLOWUP_ENABLED` | — | `true` | 信息不足主动追问（置 `false` 即时回退旧行为） |
| `AGENT_AUTO_TICKET_ENABLED` | — | `true` | Agent 决策后自动创建工单草稿 |
| `ADMIN_AI_ANALYSIS_ENABLED` | — | `true` | 管理端工单 AI 分析端点 |

## 11. API / 接口说明

认证方式：除 `/api/health`、`/api/auth/*` 外均需登录 Cookie（`agent_session`，HttpOnly）；`/api/admin/*` 需 admin 角色。完整交互式文档见 `/docs`。

| 模块 | 端点 | 说明 |
| --- | --- | --- |
| 健康检查 | `GET /api/health` | 探测 SQLite + Chroma，异常降级 degraded |
| 认证 | `POST /api/auth/register` `/login` `/logout`，`GET /api/auth/me` | 注册 / 登录 / 登出 / 当前用户 |
| 会话 | `POST GET /api/conversations`，`GET PATCH DELETE /api/conversations/{id}` | 会话 CRUD（删除级联清消息/query_log/附件） |
| 附件 | `POST GET /api/conversations/{id}/attachments`，`GET DELETE .../{attachment_id}` | 上传解析（magic-byte MIME 校验）/ 列表 / 下载 / 删除 |
| 对话 | `POST /api/chat`（SSE，10/min） | 流式问答，事件协议见 6.6 |
| 工单（用户） | `POST /api/tickets/from-conversation`（幂等）、`GET /api/tickets`、`PATCH /api/tickets/{id}/draft`、`POST .../submit` `/messages` `/confirm-resolution` `/reopen` | 建草稿 / 我的工单 / 编辑草稿 / 提交 / 补充信息 / 确认解决 / 重开 |
| 工单（管理） | `GET /api/admin/tickets`（状态/优先级/安全等级/负责人筛选）、`GET PATCH /api/admin/tickets/{id}`、`POST .../events` | 队列 / 详情 / 状态·指派·结案摘要 / 公开回复或内部备注 |
| 管理端 Copilot | `POST /api/admin/tickets/{id}/ai-analysis`（admin） | AI 诊断 + 处理建议 + 回复草稿，结果持久化为 `agent_suggestion` 审计事件（用户侧不可见） |
| 反馈 | `PUT /api/feedback`，`GET /api/feedback/stats`（admin） | 按条反馈（upsert）与统计 |
| 管理 | `GET POST /api/admin/users`，`PATCH /api/admin/users/{id}/status`，`POST .../password`，`DELETE .../{id}`，`GET /api/admin/logs`，`POST /api/admin/knowledge-base/import` | 用户管理 / 日志 / 知识库导入 |
| 索引 | `POST /api/index/rebuild`（admin，1/min） | 重建向量索引与知识图谱 |
| 图谱 | `GET /api/graph` | 读取 `kg.json`，ETag/304 缓存 |

工单状态机：`draft → submitted → assigned → in_progress → (waiting_user) → resolved_pending_confirm → closed / reopened`，取消（cancelled）与关闭（closed）为终态；允许的转换集中在 `backend/app/services/ticket_service.py` 的 `ALLOWED_TRANSITIONS`。Agent 可自动创建草稿（`actor=agent`，每会话幂等，高风险首轮不建单），但一切状态转换仍仅限人工；普通用户仅能访问自己的工单（跨用户统一 404），内部备注与 `agent_suggestion` 事件不下发普通用户，`safety_level=high` 的工单禁止系统自动关闭。

## 12. 测试与评估

**后端**（pytest **488 passed**：Stage 0 基线 413 + Agent 改造新增 75，覆盖图路由、追问守卫、诊断 schema、决策规则、工单分析服务、RAG、认证、附件、工单、API）：

```bash
cd backend
python -m pytest -q
python -m compileall -q app eval
```

**前端**（Vitest **116 passed**，25 个测试文件：api / components / stores / router / utils）：

```bash
cd frontend
npm test          # vitest run
npm run build     # vue-tsc 类型检查 + vite 构建
```

**真实在线评估**：评估集 `backend/eval/dataset.json` **v2.1**（47 题 = 34 既有 + 13 新增场景，共 17 类；由 `build_dataset.py` 从 `data/drone` 文档身份生成），进程内以 ASGI 启动完整后端（DeepSeek + 本地 embedding/reranker + Chroma + 隔离临时 SQLite）真实跑通 `/api/chat` SSE 链路：

```bash
cd backend
python eval/build_dataset.py
python -m pytest -q tests/unit/test_eval.py
python eval/run_eval.py --limit 1          # 真实跑通需 API key；--offline 为结构自检
```

47 题覆盖原 34 题（飞行安全 6、SOP 5、故障排查 4、跨机型陷阱 3、模拟案例 3、产品型号 2、时效性 2、闲聊 2、人工升级 2、技术原理 2、产品参数 1、合规法规 1、知识库缺口 1）+ 13 题新场景（信息不足追问、追问第二轮、需人工服务、知识冲突）。gold_action 分布：answer 27 / followup 5 / create_ticket 4 / escalate 9 / 不作断言 2；45 题单轮执行 + 2 题多轮待脚本化验证。

## 13. 项目效果 / 指标

评估输出（`run_eval.py`）按五组指标组织：

| 组 | 指标 |
| --- | --- |
| 路由与意图 | `route_accuracy`、`intent_accuracy`、`product_model_accuracy`、`document_type_priority_accuracy` |
| 检索质量 | `retrieval_recall@1/3/5`、`ndcg@1/3/5`、`mrr`、`hit_at_3`、`source_hit_rate`、`non_empty_rate` |
| 生成质量 | `answer_relevance`、`answer_f1`（lexical token F1）、`keyword_coverage`、`citation_correctness`、`hallucination_rate/coverage` |
| 安全与升级 | `safety_recall`（高风险召回）、`escalation_accuracy`、`cross_model_contamination_count`（跨机型污染计数） |
| Agent 业务决策 | `action_accuracy`（四值精确匹配）、`ticket_action_accuracy`（自动建单误报/漏报）、`followup_gap_hit_rate`、`diagnosis_coverage`、`diagnosis_citation_validity` |

**首次真实在线基线（2026-09-26，47 题集执行 45 题）**——此前无人机版评估集从未真实跑通（评估脚本缺登录逻辑，本次修复），以下为第一份真实数字（报告 `backend/eval/reports/report_20260926_141228.json`）：

| 指标 | 数值 | 说明 |
| --- | --- | --- |
| action_accuracy | 65.1% | 15 题不符：6 道 escalate 误报（非排查意图触发低置信升级链，方向保守）+ 4 道 service_needed 漏报等 |
| ticket_action_accuracy | 86.7% | **误报 0**（39 道 gold=False 全部未建单）；4 道 service_needed 漏报 |
| followup_gap_hit_rate | 90% | 追问缺口命中 gold 缺口的平均比例 |
| diagnosis_coverage / citation_validity | 100% / 100% | 23 题 local 路径全部产出诊断，引用全部锚定真实证据（程序校验生效） |
| safety_recall / cross_model_contamination | 100% / 0 | 6 道高风险题全部 escalate 且**无一自动建单**（"高风险首轮不自动建单"真实生效） |
| route_accuracy / intent_accuracy | 68.9% / 84.4% | 路由偏保守：9 道 local 走 online、4 道走 followup——既有路由策略首次被测量，非本次改造引入 |
| citation_correctness / escalation_accuracy | 91.3% / 80% | |
| product_model_accuracy / document_type_priority_accuracy | 100% / 82.9% | |
| hallucination_suspected | 10 条（28.6%） | 其中 9 条在 online 路径（质量检查对 Tavily 摘要偏保守），1 条 local |

**历史结果（v1.1，2026-08，旧路由 + 20 题自测集）**：`route_accuracy` 0.95 → 1.0（修复时效性误路由、答案复述、Tavily 静默失败后）。对应旧版拓扑，与当前数字不可比；也不存在"改造前后对比"——无人机版评估集改造前从未真实执行，任何 before 数字都是不存在的。

**诚实声明**：全部 gold 标签 `gold_status=inferred`，未逐题人工复核，`action_accuracy` 等 gold 本身可能有偏差；真实评估含 LLM 随机性（temperature 0.2–0.7），单次运行有波动、未多轮取均值；2 道多轮追问场景尚未脚本化验证。无真实 API key / GPU / 联网时指标为 `null` 或标记未执行，不会用猜测填充。以上数字不构成生产质量承诺；失败案例完整分析见 [agent_upgrade_eval.md](docs/evaluation/agent_upgrade_eval.md)。

## 14. Demo / 截图

`demo/` 目录已包含演示素材：**无人机售后Agent_演示.mp4**（约 4MB，配 `captions.srt` 字幕，由 `build_timeline.py` 从 `raw/` 79 张关键帧截图合成；该目录暂未纳入 git）。五分钟体验流程：

1. **登录**：管理员账号登录（首次启动由 `.env` 创建），进入聊天页。
2. **问答**：依次提问——"Mini 4 Pro 的最大图传距离"（参数）、"电池充电时鼓包了怎么办"（安全）、"飞机总是往一边偏"（信息不足 → Agent 主动追问）、"刚换了 GPS 还是不定位"（排查失败 → 触发升级）；观察 SSE 流式输出、TraceTimeline 节点逐个点亮、底部来源卡片（注意 `synthetic` 案例标注）。
3. **附件**：上传一份日志文件，追问相关问题，回答引用"用户附件"来源。
4. **工单**：点击升级提示旁的工单按钮，查看服务端生成的草稿（机型/故障分类/安全等级快照），编辑后提交；切到 `/tickets` 查看进度。
5. **管理台**：`/admin` 处理工单（接单 → AI 分析面板生成诊断与回复草稿 → 采用预填 → 人工发送 → 待确认），查看反馈统计与日志。
6. **知识图谱**：`/graph` 力导向图，点击节点"一键提问"。

## 15. 项目难点与解决方案

| 难点 | 方案 | 权衡 |
| --- | --- | --- |
| 相关性/质量判断的 LLM 成本与延迟 | 重排分数三级短路（top1≥0.5 判相关；质量均分 >0.7 通过 / <0.3 不通过），灰区才调 LLM | 本地重排 <100ms vs LLM 1–3s；只有灰色地带才付 LLM 成本 |
| 时效性问题被本地知识库"截胡"（"2026 最新…"命中旧文档） | 时效性关键词命中则跳过检索短路，强制走联网判断 | 牺牲少量本地命中，换时效正确性 |
| 幻觉检查 + 质量评估两次 LLM 调用拖慢尾部延迟 | 合并为 `combined_quality_check` 一次判定 | 调用 6 → 5 次，端到端延迟降 1–2s |
| CRAG 纠正回路死循环风险 | `correction_count` 上限 1 次，重试仍失败转联网 | 平衡"浪费本地知识库"与"无限循环" |
| 跨机型污染 | 元数据硬过滤 + 明确机型时严格排除他机型文档 + 无命中回退通用文档 + 评估集 `cross_model_trap` 专项 + `cross_model_contamination_count` 指标 | 宁可扩大范围也不答错机型 |
| DeepSeek 不支持 JSON mode | `with_structured_output(method="function_calling")` + 输出清洗与关键词兜底 | LLM 失败时降级为规则推断，不阻塞流程 |
| LLM 编造证据引用 | 诊断 citations 程序校验（⊆ 检索证据 id）：非法即弃、全部无效则置信度归零 | 真实评估 23/23 引用全部有效 |
| LLM 业务决策不可控、不可审计 | `decide_action` 零 LLM：G0 escalate → G1 followup → G2 create_ticket → G3 answer 规则阶梯，judge_log 记录触发规则与信号快照 | 行动可解释可回放；LLM 只当信号源 |
| 追问打扰体验 | 九条件守卫矩阵 + 同一会话最多连续追问 1 轮 + 高风险永不追问 | 追问轮省去检索/生成/质检约 3–4 次调用，反而更快 |
| SSE 流稳定性（代理拆包、长静默、串流） | 前端手写 SSE 解析（CRLF 归一化）、60s 无数据止损、`activeRequestId` 防串流、`final` 事件对账；后端流式不重试 + `asyncio.shield` 保日志 | 停止生成时保留已生成内容 |
| 工单状态并发一致性 | 转换白名单集中服务层 + `WHERE status=from_status` 乐观锁 + 同事务审计事件 | 任何 API 无法绕过状态机 |
| 向量库重建期间服务可用性 | 候选 collection 写完再原子替换活动指针，指纹不一致自动 rebuild | 重建失败不影响线上索引 |
| 旧库平滑升级 | 无 Alembic，各 store 基于 `PRAGMA table_info` 缺列 `ALTER TABLE`，可选列迁移后旧库仍可读 | 轻量，适合单机 SQLite 场景 |

## 16. 项目复盘

**演进时间线**：

1. **2026-08 · 评估先行**：先搭评估体系（20 题 5 类 + 6 项指标），再基于 LangGraph 做"安全优先 Corrective RAG"原型，第一轮自测把 `route_accuracy` 从 0.95 修到 1.0。
2. **2026-09-18 · 知识库迁移**：从通用 AI 学习库迁移到无人机售后知识库，71 篇文档全量补齐 frontmatter 身份字段与机型护栏。
3. **2026-09-19 · 阶段 5 收口**：评估集重建为 34 题售后集（新增安全召回、升级准确率、跨机型污染等指标），完成上线前 14 项检查（构建与健康检查通过，其余多为需生产环境的阻断项）。
4. **2026-09-20 → 09-22 · 业务闭环**：补齐认证与管理员权限、附件系统、售后工单全生命周期；知识图谱交互平滑化。
5. **2026-09-26 · Agent 增量改造（7 提交）**：新增主动追问（信息充分性 + 九条件守卫矩阵）、结构化诊断（引用程序校验）、确定性决策阶梯、Agent 自动建单草稿与管理端 AI Copilot；`rag/`、工单核心服务、认证、附件**零改动**，三项能力开关可一键回退；同时修复评估脚本登录缺陷，产出首份真实评估基线（见第 13 节）。

**做对了什么**：评估体系先行，让每次拓扑改动可回归验证；分数短路策略在成本、延迟与准确性间取得可解释的平衡；坚持诚实工程——模拟案例标注 `synthetic`、gold 未复核标注 `inferred`、已知差异（manifest 70 vs 71）记录而不掩盖。

**教训（重来会怎么改）**：评估集规模仍偏小，容易过拟合自己的直觉，应更早引入真实用户问题（当前评估集仍以 seed 为主，`from_query_log` 回流为 0）；每笔 LLM 调用的成本应从第一天开始量化；"知识图谱"目前只做可视化，未参与检索（Graph RAG），早期就应明确其边界；**"测试全绿 ≠ 真实链路可用"**——后端 413 个测试全绿，但评估脚本缺登录逻辑导致 34 题评估集从未真实跑通过，首次真实基线一跑就暴露了 6 类 escalate 误报与 4 类 service_needed 漏报，真实在线评估应与单元测试同期建立。

**诚实声明**：本项目不是 ReAct / Self-RAG，没有模型自主工具选择——业务行动由确定性规则裁决，LLM 只供给信号；评估 gold 未人工复核，离线评估不等于生产验收。上线前阻断项（生产密钥轮换、TLS/反向代理、日志脱敏审计、备份恢复演练、监控告警、GPU 压测）均未完成，详见 `RECAP.md` 与 [implementation_report.md](docs/agent/implementation_report.md)。

## 17. 后续规划

**短期（按评估报告 §6 收益排序）**
- 决策口径修正：非排查意图（product_parameter / technical_principle）跳过 diagnosis 缺失触发的 escalate（预期 action_accuracy 65% → 75%+）
- decompose 充分性提示词迭代："已排查 N 次 / 更换过部件"等自述排查历史应作为升级信号，而非判信息不足
- 时效性词表拆分："升级固件"（操作）与"最新固件版本"（求证）分流，消除 4 道 service_needed 漏报
- service_needed 漏报题回流回归集；评估 gold 逐题人工复核并置 verified；多轮追问场景脚本化验证
- SSE 自动重连与断点续传；`query_log` 真实问题回流替换 seed 题
- 修复 manifest 计数差异；生产部署（TLS / 反向代理 / 域名 / CORS）、日志脱敏审计、SQLite/Chroma 备份恢复演练、监控告警与压测

**中期**
- 图片上传与分析（故障照片）、视频诊断、设备遥测接入
- 知识图谱升级为 Graph RAG 参与检索；外部 CRM / 真实客服系统对接
- OAuth / 短信登录、多租户（当前单商家模式：工单队列不带商家选择器，`admin` 即品牌售后处理人）

## 18. License

本项目尚未附加开源 License，当前保留所有权利（代码与 `data/drone` 知识库仅供学习评估使用；知识库中的模拟案例已标注 `synthetic`）。如需开源，建议采用 MIT 或 Apache-2.0 并单独梳理数据授权。
