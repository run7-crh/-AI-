# Stage 0 开发基线（只读，未修改任何代码）

- 日期：2026-09-26
- 分支：`codex/auth-admin`
- 基线 commit：`464cb53 feat: let users edit ticket drafts before submitting`
- 工作区：`README.md` 有未提交修改（18 节模板重写，**保持原样、不入本次任何 commit**）；`docs/agent/`（阶段 1 审查报告与阶段 2 设计稿）随本基线提交入库

## 测试结果（本次实际执行）

| 检查项 | 命令 | 结果 |
|---|---|---|
| 后端测试 | `backend/.venv → python -m pytest -q` | **413 passed**（116.7s，3 warnings） |
| 后端编译 | `python -m compileall -q app eval` | 通过 |
| 前端测试 | `npm test`（vitest run） | **111 passed**（25 个测试文件，45.4s） |
| 前端构建 | `npm run build`（vue-tsc + vite） | 通过（22.0s，chunk 体积警告为既有现象，非阻塞） |

> 与记忆基线（409 后端 / 99 前端）的差异：近期 5 笔工单增强提交各带新测试，基线自然增长至 413/111。全部通过，无失败项。

## 架构状态确认（关键接线点复核）

- 13 节点图：`backend/app/graph/builder.py` 与审查报告一致，`route_after_combined_quality` 挂在 `combined_quality_check` 之后
- RAG 内核：`app/rag/*` 未被任何未提交修改触碰
- TicketService / 状态机：`app/services/ticket_service.py` 的 `ALLOWED_TRANSITIONS`、`actor_type="agent"` 预留分支在位
- SSE：`app/api/chat.py` meta 事件字段与审查报告一致
- AdminTicketDetail / AssistantMessage / query_log（27 列）/ conversation_store.get_history（当前仅返回 role/content）与审查报告一致

## 发现的问题（只记录，不修复）

1. `main.py:227` FastAPI title 仍为"学AI必备助手 API"（既有残留，Final Review 阶段顺手修正）
2. `get_history` 只返回 `{role, content}`，Stage 3 需扩展返回 `route_path`（只读查询扩展，无 schema 变更）
3. `query_log` 无 `recommended_action / diagnosis_json` 列（Stage 4 按 PRAGMA 缺列迁移先例追加）

## 结论

**READY_FOR_STAGE_3**
