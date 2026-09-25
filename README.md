# 无人机智能售后技术支持 Agent

这是一个面向无人机售后的 Agentic Workflow / Corrective RAG 原型。系统回答产品参数、型号识别、故障排查、SOP 操作、校准保养、飞行安全、合规法规和模拟案例参考问题，并在高风险场景先执行安全判断。它不宣称为具备模型自主工具选择的 ReAct 或完整 Self-RAG 系统。

## 系统目标

- 用 `data/drone` 中的结构化无人机资料回答售后问题。
- 根据意图选择文档类型优先级，并按用户明确确认的机型、部件和故障类型约束或加权检索。
- 用户没有确认机型时不强行套用具体机型；约束无命中时自动扩大检索范围，但不会把其他机型的参数或步骤当作当前机型答案。
- 高风险电池、失控、坠落、进水等问题优先给出安全处置和人工升级建议。
- 来源卡片保留文档、来源、机型、部件、故障类型、数据性质和分数；`synthetic` 资料明确显示为模拟案例，不能作为确诊依据。

## 工作流与能力

LangGraph 工作流为：

```text
rewrite_query → decompose_question
  ├─ 安全判断命中 → 安全优先的检索/回答 → quality check
  ├─ 闲聊且无设备风险 → chitchat_node → END
  ├─ 多步问题 → multi_step_reason → quality check
  └─ judge_relevance → 本地 RAG → Corrective RAG 重试 → 必要时联网回答
```

本地检索使用 Chroma + LlamaIndex，reranker 对文档类型和元数据进行排序。路由状态包含 `intent`、`metadata_constraints` 和 `document_type_priority`；安全状态包含 `safety_flag`、`safety_level`、`safety_situation` 和 `escalation_required`。这些字段会随消息和 `query_log` 持久化，旧数据库通过可选列迁移后仍可读取。

前端是 Vue 3 + Pinia。聊天保留 SSE 流式 token、停止生成、会话切换、反馈、TraceTimeline 和知识图谱页面。SSE 协议、会话、反馈、来源引用和 TraceTimeline 事件语义保持兼容。

当前已实现：无人机售后知识库 profile、意图路由、metadata 感知检索、安全优先、来源追溯、历史安全提示、query_log/反馈、流式输出、离线评估脚本和 34 题售后评估集。

当前已实现：用户名/密码注册登录、HttpOnly Cookie 服务端会话、普通用户会话与附件归属、管理员角色和后端强制鉴权。管理员可管理用户、查看反馈统计与系统日志、导入 Markdown 知识库并重建索引。

当前已实现：单商家售后工单闭环。用户可在聊天页从任意本人会话一键生成工单草稿（摘要、机型、故障分类、安全等级均由服务端从会话与 query_log 快照生成，前端传入字段不参与），确认后提交；品牌管理员在管理台按状态/优先级/安全等级/负责人筛选队列，执行接单、转派、请求补充、标记待确认、公开回复与内部备注；用户可补充信息、确认解决或重开工单。状态转换集中在服务层白名单校验并全量落审计事件，高风险工单禁止系统自动关闭。建单时可选将会话内 `ready` 附件提升为工单证据，保留期延长且过期清理跳过已绑定证据。

暂未实现：图片上传、图片分析、视频诊断、设备遥测、外部 CRM/真实客服系统对接，以及 OAuth、短信登录和多租户。

## 售后工单

第一阶段只服务一个无人机商家/品牌：现有 `admin` 账号即该品牌的售后处理人，工单队列与规则不带商家选择器，不引入 `tenant_id`。工单状态机为 `draft → submitted → assigned → in_progress → (waiting_user) → resolved_pending_confirm → closed/reopened`，允许的转换集中在 `backend/app/services/ticket_service.py` 的 `ALLOWED_TRANSITIONS`，任何 API 不得绕过。普通用户只能访问自己的工单（跨用户统一 404），内部备注只出现在管理员详情。工单证据（附件）在提升后延长保留期，`cleanup_expired` 不会删除已绑定工单的 payload。

## 知识库 profile

默认使用 `KB_PROFILE=drone`：数据目录为 `data/drone`，Chroma collection 为 `drone_kb`，读取器会把 frontmatter 元数据提升到 Evidence。需要兼容旧 AI 学习库时设置 `KB_PROFILE=obsidian`，使用 `data/raw` 和 `obsidian_kb`。显式设置旧变量 `KB_DATA_DIR` 时仍按兼容规则优先使用该目录。

`manifest.json` 当前登记 `document_count=70`，实际 Markdown 文档为 71 篇；本阶段只记录该差异，不修改 manifest。

## 启动

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
copy .env.example .env          # Windows；Linux/macOS 使用 cp
# 在 .env 中填写 DEEPSEEK_API_KEY、TAVILY_API_KEY 和 AUTH_ADMIN_PASSWORD
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

首次启动会检查 SQLite、预热 reranker，并加载或构建版本化 Chroma 索引。前端：

```bash
cd frontend
npm install
npm run dev
```

## 测试与评估

后端全量测试和 compileall：

```powershell
cd backend
$py = (Resolve-Path '.python-runtime\\cpython-3.11.16-windows-x86_64-none\\python.exe').Path
$env:PYTHONPATH = (Resolve-Path '.venv\\Lib\\site-packages').Path
& $py -m pytest -q
& $py -m compileall -q app eval
```

前端测试和构建：

```bash
cd frontend
npm test -- --run
npm run build
```

离线评估集在 [backend/eval/dataset.json](backend/eval/dataset.json)，由 [build_dataset.py](backend/eval/build_dataset.py) 从 `data/drone` 文档身份生成。当前 34 题覆盖：产品参数 1、产品型号 2、故障排查 4、SOP 5、飞行安全 6、合规 1、闲聊 2、时效 2、知识库缺口 1、跨机型陷阱 3、模拟案例 3、人工升级 2、技术原理 2。标签统一为 `gold_status=inferred`，发布前仍需人工复核。

```bash
cd backend
python eval/build_dataset.py
python -m pytest -q tests/unit/test_eval.py
python eval/run_eval.py --limit 1
```

评估脚本保留旧路由、Recall/MRR、引用和 lexical F1 字段，并新增 `intent_accuracy`、`product_model_accuracy`、`document_type_priority_accuracy`、`safety_recall`、`escalation_accuracy`、`cross_model_contamination_count`。结构化字段缺失、没有人工 gold、或没有真实 API/GPU/联网服务时，指标为 `null` 或标记未执行；不会用猜测填充。

## 上线前检查结果

| 项目 | 当前结果 | 状态 |
| --- | --- | --- |
| 密钥与环境变量 | `.env` 读取，密钥不入库；生产密钥轮换策略仍需制定 | 阻断 |
| CORS、限流、错误处理 | CORS 默认仅 localhost；slowapi 和统一错误处理已接入 | 阻断（需配置生产域名） |
| SQLite、Chroma 持久化 | SQLite WAL/迁移和版本化 Chroma 已实现 | 可延后压测 |
| 模型启动时间 | reranker 启动预热；embedding/模型冷启动仍可能较慢 | 阻断（需压测） |
| 日志脱敏 | 未发现记录 API key；查询文本可能进入日志，需生产脱敏审计 | 阻断 |
| 文件/目录权限 | 未完成生产主机权限审计 | 阻断 |
| 前后端构建 | 本阶段验证通过 | 已通过 |
| HTTPS、反向代理、域名 | 未配置，不自动部署 | 阻断 |
| 备份与恢复 | SQLite/Chroma 备份恢复演练未完成 | 阻断 |
| 监控与告警 | `/api/health` 已有；指标、日志告警未配置 | 阻断 |
| 回滚方式 | 版本化 Chroma 支持切换；应用发布回滚流程未演练 | 阻断 |
| 健康检查 | `/api/health` 探测 SQLite 和 Chroma | 已通过代码检查 |
| 生产资源 | GPU、磁盘、内存容量尚未基于压测确认 | 阻断 |
| 文档计数 | `manifest=70`、实际=71 的差异仍存在，按授权暂不修改 | 已知限制 |

## 已知限制

当前仍需补齐 SSE 自动重连、生产反向代理和 TLS。认证相关配置见 `backend/.env.example`，生产部署前必须设置非空 `AUTH_ADMIN_PASSWORD` 并启用安全 Cookie。联网、真实 API、GPU 评估依赖外部服务和模型密钥；离线单元测试不等价于上线容量或安全验收。评估集的结构化 gold 尚未逐题人工复核，不能把离线数字当成生产质量承诺。

本阶段不执行部署、不创建 PR，也不增加图片分析或人工客服能力。
