# 学AI必备助手 — 项目架构理解报告

> **文档来源**：基于对 `backend/app/`、`frontend/src/`、`pyproject.toml`、`重构任务列表.md`（两轮代码审查合并版）的直接阅读整理。
> **未读部分**：单元测试实现细节、`ChatView.vue`/`App.vue` 视图层实现、`.env.example`、`README.md`。涉及这些部分会显式标注"未读，不确定"。
> **更新日期**：2026-07-27（第二轮重构完成，对照 `重构任务列表.md` 32 项问题已部分修复）

---

## 〇、第二轮重构关键变化（对比上一版本）

| 维度 | 上一版（第一轮重构后） | 当前版（第二轮重构后） |
|------|----------------------|----------------------|
| **工作流节点** | 10 节点（无 decompose/multi_step） | 11 节点（**恢复** decompose_question + multi_step_reason） |
| **意图分类** | 无 | 新增 `decompose_question_node`：判断 is_chitchat / needs_decomposition |
| **闲聊快速通道** | 无 | 新增 chitchat 路径：直达 generate_local → END（跳过质量检查） |
| **质量评估** | 2 节点串行（hallucination_check → answer_quality_eval） | **合并为 1 节点** `combined_quality_check`（每次请求 LLM 调用从 6→5 次） |
| **judge_relevance 逻辑** | 纯 LLM 判断 | **轻量检索 + 阈值短路 + LLM 兜底**：top_k=1 reranker 分数 ≥ 0.5 直接判 relevant |
| **rag_quality_eval 逻辑** | 纯 LLM 判断 | **reranker 分数阈值短路**：>0.7 通过 / <0.3 不通过 / 灰色地带才调 LLM |
| **quality_fail 行为** | 覆盖 `final_answer` 为固定提示 | **保留 LLM 答案**，仅设置 `quality_warning` 警告文本（前端展示黄色横幅） |
| **ChatOpenAI 缓存** | 每次新建 | **模块级 `_llm_cache`** 按 `(model, temperature)` 键复用 |
| **token 计数** | 字符估算 `len*2//3` | **tiktoken `cl100k_base`** 精确计数（字符估算作 fallback） |
| **Reranker 预热** | 无 | `main.py` lifespan 中 `get_cross_encoder()` 预加载 2GB 模型 |
| **华为云配置** | 历史遗留 | **已删除** `HUAWEI_API_KEY`/`HUAWEI_BASE_URL` |
| **route_path 取值** | "local"/"online" | "local"/"online"/"chitchat"/"decomposition" |
| **state 字段** | 精简版 | 恢复 `is_chitchat`/`needs_decomposition`/`reasoning_steps`/`avg_reranker_score`/`quality_warning` |
| **知识库数据** | data/raw 20 篇 | data/raw 20 篇 + **data/processed 18 篇**（去重清理） |

> **未修复项**（来自 `重构任务列表.md` 第二轮）：P0-1（API 密钥轮换待用户手动）、P1-7（chunk 策略待确认）、P2-1/P2-3/P2-5/P2-6/P2-7/P2-9/P2-10/P2-13（前端工程化 + health 探测 + SSE 心跳等）。

---

## 一、项目架构图（文字形式）

### 1.1 分层架构

```
┌────────────────────────────────────────────────────────────────────┐
│  前端层  frontend/src/  (Vue 3 + TS + Pinia + Tailwind)             │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐         │
│  │ views/      │  │ stores/chat  │  │ api/chat.ts (SSE)   │         │
│  │ ChatView    │←─│ (状态+流控)  │←─│ api/conversations   │         │
│  │ components  │  └──────────────┘  └─────────┬───────────┘         │
│  └─────────────┘                              │                     │
└───────────────────────────────────────────────┼─────────────────────┘
                                                │ HTTP + SSE (fetch + ReadableStream)
                                                │ /api/* (Vite 代理 → :8000)
┌───────────────────────────────────────────────▼─────────────────────┐
│  API 层  backend/app/api/  (FastAPI + sse-starlette + slowapi)     │
│   chat.py        POST /api/chat        SSE 流式对话 (10/min)       │
│   conversations  CRUD /api/conversations                            │
│   index.py       POST /api/index/rebuild (1/min)                    │
│   health.py      GET  /api/health（P2-8 未升级探测，仍静态返回）   │
│   errors.py      错误码映射 + ValueError handler                    │
│   extensions.py  slowapi Limiter 单例（测试可禁用）                 │
└───────────────────────────────────────────────┬─────────────────────┘
                                                │ 调用
┌───────────────────────────────────────────────▼─────────────────────┐
│  编排层  backend/app/graph/  (LangGraph StateGraph)                │
│   builder.py  节点+条件边装配（5 个 route_after_*）                │
│   state.py    AgentState TypedDict + JudgeResult                    │
│   nodes.py    11 个 async node（rewrite/decompose/judge_relevance/ │
│                rag_retrieve/rag_quality_eval/web_search/            │
│                generate_local/generate_online/multi_step_reason/    │
│                combined_quality_check/quality_fail）                │
│   tools.py    call_llm / evaluate / retrieve / tavily_search       │
│               + _truncate_history + _estimate_tokens + _get_llm   │
│   prompts.py  9 个提示词模板 + QUALITY_FAIL_MESSAGE                │
└───────────────────────────────────────────────┬─────────────────────┘
                                                │ 调用
        ┌───────────────────────────────────────┼─────────────────────┐
        │                                       │                     │
┌───────▼──────────┐                ┌───────────▼─────────┐  ┌────────▼────────┐
│  RAG 层  rag/     │                │  外部服务           │  │  存储层          │
│  embedding.py    │                │  DeepSeek API       │  │  services/      │
│   (本地 BGE)      │                │  Tavily Search      │  │  conversation_  │
│  indexer.py       │                │  (华为云配置已删除) │  │  store.py       │
│   (Chroma 持久化) │                └─────────────────────┘  │  (SQLite +      │
│   chunk=512/50    │                                          │   tenacity重试) │
│  retriever.py     │                                          │  rag/chroma/   │
│   (BGE CrossEncoder│                                         └─────────────────┘
│    + GPU 预热)    │
│  readers.py       │
│   (Obsidian md)   │
└───────────────────┘
```

### 1.2 LangGraph 节点拓扑（第二轮重构后，含条件分支）

```
                            START
                              │
                              ▼
                       ┌─────────────┐
                       │rewrite_query│  (temp=0.7, 不传 history, 容错退回原 query)
                       └──────┬──────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │decompose_question│ (temp=0.3, structured output)
                     │ 判断 is_chitchat │
                     │ + needs_decomp.  │
                     └────────┬────────┘
                              │
                ┌─────────────┼─────────────┐
                │             │             │
        is_chitchat=true  needs_decomp=true  else
                │             │             │
                ▼             ▼             ▼
        ┌──────────────┐ ┌──────────────┐ ┌────────────────┐
        │generate_local│ │multi_step_   │ │judge_relevance │
        │(CHITCHAT_    │ │reason        │ │ (轻量检索短路) │
        │ PROMPT)      │ │(deepseek-    │ └────────┬───────┘
        └──────┬───────┘ │ reasoner,    │          │
               │         │ RAG/子问题)  │   is_relevant?
               │         └──────┬───────┘   ┌──────┴──────┐
               │                │           ▼ true        ▼ false
               │                │   ┌──────────────┐ ┌──────────┐
               │                │   │rag_retrieve  │ │web_search│
               │                │   │(top_k=9→BGE │ │(Tavily)  │
               │                │   │ 重排→3)     │ └────┬─────┘
               │                │   └──────┬───────┘      │
               │                │          │              │
               │                │          ▼              │
               │                │   ┌─────────────────┐    │
               │                │   │rag_quality_eval │    │
               │                │   │(reranker 分数   │    │
               │                │   │ 阈值短路)       │    │
               │                │   └────────┬────────┘    │
               │                │            │             │
               │                │     rag_quality_pass?    │
               │                │     ┌──────┴──────┐    │
               │                │     ▼ true        ▼ false│
               │                │ ┌────────────┐    │      │
               │                │ │generate_   │    │      │
               │                │ │local       │    │      │
               │                │ │(LOCAL_GEN) │    │      │
               │                │ └─────┬──────┘    │      │
               │                │       │           │      │
               │                │       │           ▼      │
               │                │       │  ┌─────────────────┐
               │                │       │  │generate_online  │◄┘
               │                │       │  │(ONLINE_GEN)     │
               │                │       │  └────────┬────────┘
               │                │       │           │
               └────────────────┴───────┴───────────┘
                              │           │
                              ▼           ▼
                    ┌─────────────────────────────┐
                    │combined_quality_check       │
                    │ (一次 LLM 同时评估幻觉+质量)│
                    │ source 按 route_path 取:    │
                    │   online → web_search_result│
                    │   local/decomp → retrieval   │
                    └────────────┬────────────────┘
                                 │
                    not halluc. AND quality_pass?
                    ┌────────────┴────────────┐
                    ▼ true                    ▼ false
                    END              ┌──────────────────┐
                                     │quality_fail      │
                                     │(设 quality_warning│
                                     │ 保留 final_answer)│
                                     └────────┬─────────┘
                                              │
                                              ▼
                                             END
```

**关键路由策略**（来自 `backend/app/graph/builder.py`）：
- **恢复** `decompose_question` + `multi_step_reason` 节点（P0-2，修复第一轮重构的退化）
- **新增** chitchat 快速通道：闲聊类跳过所有质量检查直达 END（P1-5）
- **合并** `hallucination_check` + `answer_quality_eval` → `combined_quality_check`（P1-1，每次请求 LLM 调用从 6→5 次）
- **judge_relevance 改用轻量检索短路**：top_k=1 reranker 分数 ≥ 0.5 直接判 relevant（修复 LLM 误判 bug）
- **rag_quality_eval 改用 reranker 分数阈值短路**：>0.7 通过 / <0.3 不通过（P1-2，省 LLM 调用）
- **quality_fail 不再覆盖 final_answer**：改为设置 `quality_warning` 警告文本（P1-3，保留 LLM 答案让用户自行判断）

### 1.3 11 个节点执行细节（来自 `backend/app/graph/nodes.py`）

| # | 节点 | 模型/工具 | 输入字段 | 输出字段 | 关键规则 |
|---|------|----------|----------|----------|----------|
| 1 | `rewrite_query` | deepseek-chat (temp=0.7) | `query` | `rewritten_query` | **不传 history**；输出含 `\n`/超 200 字/`#`/`-`/`*`/````/数字列表 → 退回原 query |
| 2 | `decompose_question` | deepseek-chat (temp=0.3, structured) | `rewritten_query` | `is_chitchat`, `needs_decomposition`, `reasoning_steps` | 判断闲聊/多步推理/正常流程 |
| 3 | `judge_relevance` | 轻量检索 + LLM 兜底 | `rewritten_query`, `query` | `is_relevant`, `judge_log` | **轻量检索短路**：top_k=1 reranker 分数 ≥ 0.5 直接判 relevant；低分用 LLM 判断（原始 query） |
| 4 | `rag_retrieve` | BGE embedding + BGE CrossEncoder | `rewritten_query` | `retrieval_result`, `avg_reranker_score` | `similarity_top_k=9` 召回 → reranker 重排 → 截 top_k=3；计算平均分 |
| 5 | `rag_quality_eval` | reranker 分数 + LLM 灰色地带 | `retrieval_result`, `avg_reranker_score` | `rag_quality_pass`, `judge_log` | **阈值短路**：>0.7 通过 / <0.3 不通过 / 0.3-0.7 调 LLM；空检索直接不通过 |
| 6 | `web_search` | Tavily API (max_results=5) | `rewritten_query` | `web_search_result` | **失败不抛异常**，返回提示字符串 |
| 7 | `generate_local` | deepseek-chat (streaming) | `query`, `rewritten_query`, `retrieval_result`, `history` | `final_answer`, `route_path="local"` | chitchat 路径用 `CHITCHAT_PROMPT`；local 用 `LOCAL_GEN_PROMPT`；retry 耗尽降级 |
| 8 | `generate_online` | deepseek-chat (streaming) | `query`, `rewritten_query`, `web_search_result`, `history` | `final_answer`, `route_path="online"` | 用 `ONLINE_GEN_PROMPT`；retry 耗尽降级 |
| 9 | `multi_step_reason` | deepseek-reasoner (streaming) | `reasoning_steps`, `query`, `history` | `final_answer`, `route_path="decomposition"`, `retrieval_result` | 对每个子问题调 RAG 检索注入 prompt；retry 耗尽降级 |
| 10 | `combined_quality_check` | deepseek-chat (temp=0.2, structured) | `final_answer`, source（按 route_path 取） | `has_hallucination`, `answer_quality_pass`, `judge_log` | **一次 LLM 同时评估幻觉+质量**；source 按 route_path 取：online→web_search_result，其他→retrieval_result |
| 11 | `quality_fail` | 无 LLM 调用 | `has_hallucination`, `answer_quality_pass` | `quality_warning` | **不覆盖 final_answer**，仅设置警告文本；has_hallucination→"未经验证信息" / quality 不通过→"未充分回答" |

### 1.4 5 个条件路由函数（来自 `backend/app/graph/builder.py`）

| 路由函数 | 判断字段 | true 分支 | false 分支 |
|---------|---------|----------|-----------|
| `route_after_decompose` | `is_chitchat` / `needs_decomposition` | `generate_local`（chitchat）/ `multi_step_reason`（decomp） | `judge_relevance` |
| `route_after_relevance` | `is_relevant` | `rag_retrieve` | `web_search` |
| `route_after_rag_quality` | `rag_quality_pass` | `generate_local` | `web_search` |
| `route_after_generate` | `route_path == "chitchat"` | END | `combined_quality_check` |
| `route_after_combined_quality` | `not has_hallucination AND answer_quality_pass` | END | `quality_fail` |

### 1.5 四条关键执行路径

**路径 A：闲聊快速通道**（最快，无质量检查）
```
rewrite_query → decompose_question(is_chitchat=true) → generate_local(CHITCHAT_PROMPT) → END
```

**路径 B：本地知识库成功**（理想路径）
```
rewrite_query → decompose_question(else) → judge_relevance(true) → rag_retrieve
→ rag_quality_eval(true) → generate_local → combined_quality_check(pass) → END
```

**路径 C：多步推理**（复杂问题）
```
rewrite_query → decompose_question(needs_decomposition=true) → multi_step_reason
→ combined_quality_check(pass) → END
```

**路径 D：本地检索质量差，回退联网**
```
rewrite_query → decompose_question(else) → judge_relevance(true) → rag_retrieve
→ rag_quality_eval(false) → web_search → generate_online → combined_quality_check(pass) → END
```

**路径 E：问题与知识库无关**
```
rewrite_query → decompose_question(else) → judge_relevance(false) → web_search
→ generate_online → combined_quality_check(pass) → END
```

**质量不合格分支**（路径 B/C/D/E 中可能触发）：
- 合并质量检查不通过 → `quality_fail`（设 `quality_warning`，保留 `final_answer`）→ END

### 1.6 与上一版的关键差异

1. **恢复 2 节点**：`decompose_question` + `multi_step_reason`（修复第一轮重构的退化，P0-2）
2. **合并 2 节点**：`hallucination_check` + `answer_quality_eval` → `combined_quality_check`（P1-1，每次请求 LLM 调用从 6→5 次）
3. **新增 chitchat 快速通道**：闲聊类跳过所有质量检查直达 END（P1-5）
4. **judge_relevance 改用轻量检索短路**：修复 LLM 把"什么是RAG"误判为通用知识的严重 bug
5. **rag_quality_eval 改用 reranker 分数阈值短路**：>0.7/<0.3 省掉 LLM 调用（P1-2）
6. **quality_fail 保留 LLM 答案**：改为设置 `quality_warning` 警告文本（P1-3，用户体验提升）
7. **ChatOpenAI 实例缓存**：按 `(model, temperature)` 键复用（P1-10）
8. **tiktoken 精确 token 计数**：替代字符估算（P1-11）
9. **Reranker 预热**：main.py lifespan 中预加载 2GB 模型（P0-3）

---

## 二、核心模块说明

### 2.1 前端层（`frontend/src/`）

| 模块 | 职责 | 关键文件 |
|------|------|----------|
| **视图** | 单页聊天界面路由 | `frontend/src/views/ChatView.vue` *（未读细节）* |
| **Store** | 会话/消息/流状态管理，AbortController 中止控制 | `frontend/src/stores/chat.ts` |
| **SSE 客户端** | `fetch` + `ReadableStream` 解析 `sse-starlette` 事件，60s 无数据超时 | `frontend/src/api/chat.ts` |
| **会话 API** | conversations CRUD | `frontend/src/api/conversations.ts` *（未读细节）* |
| **类型** | 与后端 `backend/app/models/schemas.py` 镜像对齐 | `frontend/src/types/index.ts` |

**Store 关键设计**：
- `streamChat()` 通过 5 个回调 (`onStage/onToken/onMeta/onError/onDone`) 把 SSE 事件分发到响应式消息对象
- `stopStreaming()` 区分用户主动中止 vs 错误中止：主动中止保留已生成内容
- 切换/新建会话前主动 `stopStreaming()` 避免旧流污染新会话
- **未修复**：消息 ID 仍用 `Date.now()`（P2-6 未修），SSE 无心跳重连（P2-5 未修）

### 2.2 API 层（`backend/app/api/`）

| 路由 | 文件 | 行为要点 |
|------|------|----------|
| `POST /api/chat` | `backend/app/api/chat.py` | SSE，事件类型 `stage/token/meta/error/done`；先校验会话 404；**`@limiter.limit("10/minute")`**；通过 `config.metadata.conversation_id` 关联日志；`meta` 事件含 `quality_warning` |
| `GET/POST/PATCH/DELETE /api/conversations` | `backend/app/api/conversations.py` | 标准 CRUD |
| `POST /api/index/rebuild` | `backend/app/api/index.py` | 同步重建 Chroma 索引；**`@limiter.limit("1/minute")`** |
| `GET /api/health` | `backend/app/api/health.py` | **P2-8 未修**：仍只返回静态字段，未探测 DB/向量库可达性 |
| 错误处理 | `backend/app/api/errors.py` | 错误码映射 + ValueError handler；**P2-7 未修**：`ERROR_STATUS_CODE` 映射未实现 |
| 限速器单例 | `backend/app/extensions.py` | `Limiter(key_func=get_remote_address)`，测试环境 `SLOWAPI_ENABLED=false` 可禁用 |

**Chat SSE 关键设计**（`backend/app/api/chat.py:45-167`）：
- 用 `graph.astream_events(input_state, version="v2", config=runnable_config)` 捕获 LangGraph 事件
- `runnable_config["metadata"]["conversation_id"]` 透传到 `call_llm` 用于日志关联
- `on_chain_start` → 推 `stage` 事件（11 个阶段标签，含 `decompose_question`/`multi_step_reason`/`combined_quality_check`）
- `on_chat_model_stream` / `on_llm_stream` → 推 `token` 事件（前端逐字渲染）
- `on_chain_end (name=="LangGraph")` → 取 `final_state`，落库 assistant 消息 + 推 `meta` 事件
- `meta` 事件含 `quality_warning`（P1-3，仅 quality_fail 路径有值）
- 异常时用 `logger.exception()` 统一记录（P1-9 已修，移除手写 errors.log）

### 2.3 编排层（`backend/app/graph/`）

#### `tools.py` — 4 个原子工具 + 3 个辅助函数

| 工具/函数 | 签名 | 关键点 |
|-----------|------|--------|
| `call_llm` | `async (system_prompt, user_input, temperature, output_schema?, history?, model, stream?, config?)` | `@retry(3, 指数退避1-8s, ValueError不重试)`；structured output 用 `function_calling`；stream 聚合 chunk；从 `config.metadata.conversation_id` 提取日志标签；**P1-10: 用 `_get_llm` 缓存 ChatOpenAI 实例** |
| `evaluate` | `async (judge_type, source, answer?, query?)` | 统一 `temp=0.2`；仅 2 种 `judge_type`：`is_relevant`/`is_retrieval_quality`（幻觉+答案质量已合并到 combined_quality_check_node，不再走 evaluate） |
| `retrieve` | `async (query, rag_retriever, top_k=3)` | `asyncio.to_thread` 包装同步 retriever |
| `tavily_search` | `async (query, max_results=5)` | **失败不抛异常**，返回提示字符串 |
| `_get_llm` | `(model, temperature) -> ChatOpenAI` | **P1-10**：按 `(model, temperature)` 键缓存 ChatOpenAI 实例到模块级 `_llm_cache` |
| `_estimate_tokens` | `(text) -> int` | **P1-11**：用 tiktoken `cl100k_base` 精确计数；加载失败退回 `len*2//3` |
| `_truncate_history` | `(history, max_tokens=6000) -> list` | 按预算从最新向前保留，单条超长也保留 |

#### `nodes.py` — 11 个 LangGraph 节点（详见 §1.3）

#### `state.py` — 状态定义

`AgentState` TypedDict（第二轮重构后）：
- **输入**：`query` / `conversation_id` / `history`
- **意图分类**：`is_chitchat` / `needs_decomposition` / `reasoning_steps`（P0-2 恢复）
- **中间产物**：`rewritten_query` / `is_relevant` / `retrieval_result` / `avg_reranker_score`（P1-2 新增）/ `rag_quality_pass` / `web_search_result`
- **质量评估**：`has_hallucination` / `answer_quality_pass`
- **输出**：`final_answer` / `route_path`（"local"/"online"/"chitchat"/"decomposition"）/ `quality_warning`（P1-3 新增，不覆盖 final_answer）
- **审计日志**：`judge_log: Annotated[list[JudgeResult], add]`

#### `prompts.py` — 9 个提示词模板 + 1 个固定文本

| Prompt | 用途 | 关键点 |
|-------|------|--------|
| `REWRITE_PROMPT` | 问题改写 | 5 条约束 + 错误示例 + 正确示例 |
| `DECOMPOSE_PROMPT` | 意图分类 + 问题分解 | 判断 is_chitchat / needs_decomposition；明确"宁可不分解"原则 |
| `IS_RELEVANT_PROMPT` | KB 相关性判断 | passed=true 相关，passed=false 需联网 |
| `IS_RETRIEVAL_QUALITY_PROMPT` | 检索质量评估（LLM 灰色地带） | 判断检索内容能否回答问题 |
| `LOCAL_GEN_PROMPT` | 本地生成 | 要求 `[来源：文档片段 X]` 标注 |
| `ONLINE_GEN_PROMPT` | 联网生成 | 要求 `[来源：URL 或网站名]` 标注 |
| `CHITCHAT_PROMPT` | 闲聊快速通道 | 简洁友好，不引用知识库 |
| `MULTI_STEP_PROMPT` | 多步推理 | 按子问题逐步推理，用 `[来源：文档片段 X]` 标注 |
| `IS_COMBINED_QUALITY_PROMPT` | 合并质量评估 | **一次 LLM 同时评估幻觉+质量**；"宁可宽松判定" |
| `QUALITY_FAIL_MESSAGE` | 质量不合格固定提示 | 固定文本（现在仅作为 quality_fail 的 fallback） |

### 2.4 RAG 层（`backend/app/rag/`）

| 模块 | 职责 | 关键点 |
|------|------|--------|
| `embedding.py` | 配置 LlamaIndex 全局 embed_model | **P2-2 已修**：移除模块导入副作用，改为 `Indexer.__init__` 显式调用；本地 `BAAI/bge-large-zh-v1.5`（dim=1024） |
| `readers.py` | Obsidian `.md` 读取器 | 处理 wikilink/callout/embed/frontmatter；`tags` list 展平为逗号串 |
| `indexer.py` | Chroma 持久化 + 索引构建 | `chunk_size=512, chunk_overlap=50`；`load_or_build()` 检查 `count()==0` 触发 rebuild |
| `retriever.py` | 向量检索 + Reranking | `BGEReranker` 用 `sentence-transformers.CrossEncoder` 调本地 `BAAI/bge-reranker-v2-m3`；模块级 `_cross_encoder_cache`；**P0-3: GPU 加速 + main.py 预热**；`similarity_top_k=9` 召回 → reranker 重排 → 截 top_k=3 |

> **重要变化**（标注信心程度：高）：
> - **P0-3 已修**：`main.py` lifespan 中调用 `get_cross_encoder(settings.RERANKER_MODEL)` 预加载 2GB 模型，避免首次请求卡顿；`CrossEncoder` 初始化时显式 `device='cuda' if torch.cuda.is_available() else 'cpu'`
> - **P0-4 已修**：`config.py` 已删除 `HUAWEI_API_KEY`/`HUAWEI_BASE_URL`，华为云配置完全清理

### 2.5 服务层（`backend/app/services/`）

`ConversationStore`：SQLite + aiosqlite，两张表：
- `conversations(id, title, created_at, updated_at, message_count)`
- `messages(id, conversation_id, role, content, route_path, sources, judge_log, created_at)`，`sources/judge_log` 以 JSON 字符串存
- 索引：`idx_messages_conversation(conversation_id, created_at)`

**P1-4 已修**：写操作（`create_conversation`/`add_message`/`delete_conversation`/`update_conversation_title`）加 `@_db_retry` 装饰器（3 次重试，指数退避 0.1-1.0s，覆盖 `sqlite3.OperationalError`）。
**P2-9 未修**：`get_conversation`/`list_conversations`/`get_history` 仍无 `@_db_retry`（读操作冲突概率低）。

> **观察**（标注信心程度：中）：仍每操作新建 connection（无连接池）。`add_message` 在同一事务内 INSERT message + UPDATE conversation（原子性保证）。

### 2.6 配置与启动

`backend/app/config.py`（`pydantic-settings` BaseSettings，从 `.env` 读）：
- DeepSeek API + base_url
- **P0-4 已修**：华为云 API 配置已删除
- Tavily key
- **P1-3 已修**：`KB_DATA_DIR` 改为 `_PROJECT_ROOT/data/raw` 相对路径
- **P2-12 已修**：`CHROMA_COLLECTION_NAME` 可配置（默认 `obsidian_kb`）
- `EMBEDDING_CACHE_DIR` / `RERANKER_CACHE_DIR`（锚定到项目内）
- 模型映射：`flash→deepseek-chat` / `pro_chat→deepseek-chat` / `pro_reason→deepseek-reasoner`

`backend/app/main.py` lifespan：
1. **P1-9 已修**：`RotatingFileHandler`（10MB×5，UTF-8）+ `logger.exception()` 统一
2. 初始化 `ConversationStore` + 注入 conversations 模块
3. **P0-3 已修**：Reranker 预热（`get_cross_encoder(settings.RERANKER_MODEL)`）
4. **try/except 初始化 graph**：失败降级到 None，不阻塞应用启动
5. CORS：`["http://localhost:5173", "http://localhost:4173"]`
6. **P1-8 已修**：注册 slowapi limiter 到 `app.state` + `RateLimitExceeded` handler

---

## 三、数据流说明

### 3.1 一次对话的完整数据流（用户发问 → 答案落库）

```
[用户在前端输入 "什么是 RAG？"]
    │
    ▼
[stores/chat.ts: sendMessage()]
    - 创建 userMsg + assistantMsg（isStreaming=true）
    - 创建 AbortController
    ▼
[api/chat.ts: streamChat()]
    POST /api/chat  { conversation_id, message }
    Accept: text/event-stream
    ▼
[backend/app/api/chat.py: chat_stream()]
    1. store.get_conversation(conv_id) → 不存在返回 404
    2. store.add_message(role="user", content=message)  ← @_db_retry
    3. store.get_history(limit=10) 取最近 10 条
    4. input_state = {query, conversation_id, history[:-1], judge_log:[]}
    5. runnable_config = {metadata: {conversation_id}}  ← P2-5 日志关联
    6. graph.astream_events(input_state, version="v2", config=runnable_config)
    ▼
[LangGraph 执行] —— 各节点产出 state 字段
    rewrite_query        → rewritten_query
    decompose_question   → is_chitchat, needs_decomposition, reasoning_steps
    分支路由（chitchat/decomp/正常）...
    judge_relevance      → is_relevant（轻量检索短路）
    rag_retrieve         → retrieval_result, avg_reranker_score
    rag_quality_eval     → rag_quality_pass（reranker 阈值短路）
    web_search           → web_search_result
    generate_local/online/multi_step_reason → final_answer, route_path
    combined_quality_check → has_hallucination, answer_quality_pass
    quality_fail         → quality_warning（不覆盖 final_answer）
    ▼
[chat.py: event_generator()] —— 边执行边推 SSE
    on_chain_start  → {"type":"stage","data":"正在检索知识库..."}
    on_chat_model_stream → {"type":"token","data":"检"} {"type":"token","data":"索"}...
    on_chain_end(LangGraph) → 取 final_state
    ▼
[落库] store.add_message(
        role="assistant",
        content=final_answer,
        route_path=route_path,
        sources=sources_for_meta,  # online 路径为空数组
        judge_log=final_state.judge_log
       )  ← @_db_retry
[推 meta 事件] → {"type":"meta","data":{
    route_path, sources, judge_log,
    quality_warning  ← P1-3 新增（仅 quality_fail 路径有值）
}}
[推 done 事件] → {"type":"done"}
    ▼
[前端 streamChat 解析]
    - sse-starlette 用 \r\n 行尾，前端规范化为 \n
    - 60s 无数据超时 → reader.cancel()
    - dispatchEvent → onStage/onToken/onMeta/onError/onDone
    ▼
[stores/chat.ts: 回调更新 messages.value 末尾的 assistantMsg]
    onStage → m.currentStage = stage
    onToken → m.content += token
    onMeta  → m.route_path/sources/judge_log/quality_warning 赋值
    onDone  → m.isStreaming = false
```

### 3.2 RAG 索引构建数据流

```
Indexer.__init__  → configure_embedding()（P2-2 显式调用）
                   → Settings.chunk_size=512, chunk_overlap=50
                   → Chroma PersistentClient + collection(CHROMA_COLLECTION_NAME)
    ▼
load_or_build()   → 检查 collection.count()==0
                    ├─ 为空 → build() 全量重建
                    └─ 非空 → VectorStoreIndex.from_vector_store
                              失败 → build()
    ▼
build()           → for each *.md in data_dir:
                       ObsidianMarkdownReader.load_data(file)
                    VectorStoreIndex.from_documents(documents, storage_context)
                       → 内部按 chunk_size=512 切分
                       → 调用 Settings.embed_model (本地 BGE) 向量化
                       → 写入 Chroma collection
    ▼
get_retriever()   → RAGRetriever(index, top_k=3)
                    内含 VectorIndexRetriever(similarity_top_k=9) + BGEReranker
```

### 3.3 三类 Memory / 上下文注入机制

> 标注信心程度：高

项目**没有显式的 Memory 模块**。"记忆"由三种机制拼装：

1. **对话历史**（短期记忆）：`get_history(conv_id, limit=10)` 取最近 10 条 → 注入 `AgentState.history` → `call_llm` 中 `_truncate_history` 按 6000 token 预算截断（P1-9）→ 转成 `HumanMessage/AIMessage` 列表
   - **特例**：`rewrite_query_node` 和 `judge_relevance_node` 故意不传 history（避免污染客观判断）
2. **会话状态持久化**（长期记忆）：`messages` 表存所有消息 + `route_path/sources/judge_log`，下次进入会话 `get_conversation` 全量返回
3. **LangGraph State**（单次执行内记忆）：`AgentState` 在节点间传递中间产物

### 3.4 两级短路机制（第二轮重构核心优化）

> 标注信心程度：高

**judge_relevance 轻量检索短路**（修复 LLM 误判 bug）：
```
1. 用 rewritten_query 做轻量检索（top_k=1）
2. reranker 分数 >= 0.5 → 直接判 relevant=true（跳过 LLM，省 1 次调用）
3. 低分或无结果 → 用 LLM 判断（原始 query）
```

**rag_quality_eval reranker 分数阈值短路**（P1-2）：
```
1. avg_reranker_score > 0.7 → 直接通过（省 1 次 LLM 调用）
2. avg_reranker_score < 0.3 → 直接不通过（省 1 次 LLM 调用）
3. 0.3 <= avg_score <= 0.7 → 灰色地带，调 LLM 精细判断
4. 空检索结果 → 直接不通过
```

**combined_quality_check 合并评估**（P1-1）：
```
一次 LLM 调用同时评估幻觉 + 答案质量（从 2 次 LLM 降到 1 次）
source 按 route_path 取：
  - online → web_search_result
  - local/decomposition → retrieval_result
  - chitchat → 不走此节点（route_after_generate 跳过）
```

---

## 四、当前技术栈分析

### 4.1 技术栈清单

| 层 | 技术 | 版本约束 | 实际选型 |
|----|------|----------|----------|
| 后端框架 | FastAPI | `>=0.110.0` | + sse-starlette `>=2.0.0` |
| ASGI 服务器 | uvicorn[standard] | `>=0.27.0` | 单进程 |
| LLM 编排 | LangGraph | `>=0.2.0` | StateGraph + astream_events(v2) |
| LLM 客户端 | langchain-openai | `>=0.1.0` | ChatOpenAI（OpenAI 兼容协议调 DeepSeek） |
| RAG 框架 | LlamaIndex | `>=0.10.0` | VectorStoreIndex + VectorIndexRetriever |
| 向量库 | Chroma | `>=0.5.0` | PersistentClient 本地文件 |
| Embedding | HuggingFace BGE | 本地 `BAAI/bge-large-zh-v1.5` | dim=1024 |
| Reranker | sentence-transformers CrossEncoder | 本地 `BAAI/bge-reranker-v2-m3` | **P0-3: GPU 加速 + 预热** |
| 联网搜索 | tavily-python | `>=0.3.0` | basic 模式 |
| LLM | DeepSeek 官方 API | — | `deepseek-chat` + `deepseek-reasoner` |
| 重试 | tenacity | `>=8.2.0` | `@retry(3, 指数退避)` + DB `OperationalError` 重试 |
| 数据校验 | pydantic + pydantic-settings | `>=2.6.0` | v2 |
| 数据库 | SQLite + aiosqlite | `>=0.19.0` | 文件型 |
| Markdown 解析 | python-frontmatter | `>=1.1.0` | Obsidian frontmatter |
| API 限速 | slowapi | `>=0.1.9` | **P1-8 已加** |
| token 计数 | tiktoken | **未在 pyproject 声明** | **P1-11 已加**（cl100k_base） |
| 前端框架 | Vue 3 | `^3.5.12` | Composition API + `<script setup>` |
| 状态管理 | Pinia | `^4.0.2` | setup-style store |
| 路由 | vue-router | `^4.6.4` | — |
| 构建 | Vite | `^5.4.10` | + `@vitejs/plugin-vue` |
| 类型 | TypeScript | `~5.6.2` | `vue-tsc` 类型检查 |
| 样式 | Tailwind CSS | `^3.4.19` | 无组件库 |
| Markdown 渲染 | markdown-it + highlight.js | `^14.3.0` / `^11.11.1` | — |
| 测试（后端） | pytest + pytest-asyncio + pytest-cov | — | asyncio_mode=auto |
| 测试（前端） | vitest + @vue/test-utils + jsdom | — | — |

> **依赖声明不全问题**（标注信心程度：高）：`pyproject.toml` 缺少 `tiktoken`、`sentence-transformers`、`torch` 三个实际使用的依赖声明。运行时能工作是因为这些包被其他依赖间接安装，但全新环境部署会失败。

### 4.2 技术栈评价（针对"生产级 AI 应用"标准，对照重构任务列表第二轮）

| 维度 | 评价 | 信心 | 对应任务 |
|------|------|------|----------|
| **架构合理性** | ✅ 恢复多步推理 + chitchat 快速通道 + 合并质量检查，架构更完整 | 高 | P0-2/P1-1/P1-5 |
| **RAG 实现** | ✅ Reranker 真实生效 + GPU 预热；chunk 策略合理；两级短路优化 | 高 | P0-3/P1-2 |
| **流式输出** | ✅ SSE 端到端打通，token 级流式 + stage 进度，含超时/中止控制 | 高 | — |
| **错误处理** | ⚠️ 节点层 try/except 降级（保留）；日志已统一到 `logger.exception()` + RotatingFileHandler | 高 | P1-9 |
| **可观测性** | ⚠️ conversation_id 日志关联已加；但无 metrics、无 tracing、health 接口仍只返回静态字段未探测 | 高 | P2-8 未修 |
| **并发与连接池** | ⚠️ SQLite 每操作新建 connection；DB 重试已加；**ChatOpenAI 实例缓存已加** | 中 | P1-4/P1-10 |
| **安全性** | ⚠️ API 限速已加；但仍无认证、CORS 写死 localhost、P0-1 API 密钥泄露待用户手动轮换 | 高 | P1-8/P0-1 |
| **配置管理** | ✅ KB_DATA_DIR 相对路径；Chroma collection 可配置；华为云配置已清理 | 高 | P1-3/P2-12/P0-4 |
| **测试覆盖** | ✅ 单元测试 12 个文件 + 集成测试 4 个 API + e2e 1 个 | 高 | — |
| **依赖管理** | ❌ pyproject 用 `>=` 而非锁定版本；**tiktoken/sentence-transformers/torch 未声明** | 高 | — |
| **前端工程质量** | ⚠️ TS strict + 单元测试 + AbortController 流控；但消息ID 仍用 Date.now、SSE 无心跳、HelloWorld.vue 未删 | 高 | P2-1/P2-5/P2-6 |
| **上下文管理** | ✅ History token 预算截断 + tiktoken 精确计数 | 高 | P1-9/P1-11 |
| **Prompt 工程** | ✅ 检索质量与答案质量 prompt 拆分；合并质量评估 prompt；chitchat/multi_step prompt | 高 | P1-6/P1-1 |
| **LLM 调用优化** | ✅ ChatOpenAI 实例缓存 + 两级短路（省 LLM 调用）+ 合并质量评估 | 高 | P1-1/P1-2/P1-10 |

### 4.3 与设计文档的偏差点（标注信心程度：高）

1. **Embedding 提供方偏离**：设计文档 §3 写"Embedding = 华为云 MaaS bge-large-zh-v1.5"，实际用本地 HuggingFace 同名模型。功能等价，部署形态不同。**P0-4 已清理华为云配置**。
2. **Reranker 提供方偏离**：设计文档写"Reranker = 华为云 MaaS bge-reranker-v2-m3"，实际改为本地 `BAAI/bge-reranker-v2-m3`（sentence-transformers CrossEncoder）。**P0-3 已加 GPU 加速 + 预热**。
3. **非目标声明**：设计文档 §1.3 明确"不做用户系统/权限隔离、不做多知识库、不做生产级监控/告警"——意味着如果"生产级标准"包含这些，**需要与用户确认是否调整非目标边界**，而不是直接补做。

---

## 五、重构任务列表执行情况（对照 `重构任务列表.md` 第二轮 32 项）

### 5.1 已修复（18 项）

| 任务 | 状态 | 修改文件 |
|------|------|----------|
| P0-2 Reranker 真实实现 | ✅ | `rag/retriever.py`（BGEReranker + CrossEncoder） |
| P0-3 Reranker GPU 加速 + 预热 | ✅ | `rag/retriever.py` + `main.py`（lifespan 预热） |
| P0-4 删除华为云配置 | ✅ | `config.py` |
| P1-1 合并质量评估节点 | ✅ | `nodes.py`/`builder.py`/`prompts.py`（combined_quality_check） |
| P1-2 rag_quality_eval 阈值短路 | ✅ | `nodes.py`/`state.py`（avg_reranker_score） |
| P1-3 quality_fail 保留答案 | ✅ | `nodes.py`/`state.py`/`api/chat.py`（quality_warning） |
| P1-4 DB 事务+重试 | ✅ | `services/conversation_store.py`（`@_db_retry`） |
| P1-5 闲聊快速通道 | ✅ | `nodes.py`/`builder.py`/`prompts.py`（chitchat） |
| P1-6 联网 prompt 传 source | ✅ | `nodes.py`（合并节点自然解决） |
| P1-8 API 速率限制 | ✅ | `extensions.py`/`api/chat.py`/`api/index.py` |
| P1-9 日志统一 | ✅ | `main.py`（RotatingFileHandler）/`api/chat.py`（logger.exception） |
| P1-10 ChatOpenAI 实例缓存 | ✅ | `graph/tools.py`（`_llm_cache`） |
| P1-11 token 精确计数 | ✅ | `graph/tools.py`（tiktoken cl100k_base） |
| P0-2(新) 恢复多步推理 | ✅ | `nodes.py`/`builder.py`/`state.py`/`prompts.py` |
| P1-9(旧) Context 窗口管理 | ✅ | `graph/tools.py`（`_truncate_history`） |
| P2-5(旧) conversation_id 日志 | ✅ | `api/chat.py`（config.metadata） |
| P2-12 Chroma collection 可配置 | ✅ | `config.py`/`rag/indexer.py` |
| P2-2 embedding 副作用 | ✅ | `rag/embedding.py`/`rag/indexer.py` |

### 5.2 未修复（11 项）

| 任务 | 优先级 | 说明 |
|------|--------|------|
| P0-1 API 密钥轮换 | P0 | 需用户在控制台手动操作 + git 历史清理 |
| P1-7 Chunk 策略 | P1 | 待确认（代码已有 512/50，但未用 MarkdownNodeParser） |
| P1-4(新) Query Rewrite 传 history | P1 | 仍不传，容错逻辑保留（设计权衡） |
| P2-1 删除 HelloWorld.vue | P2 | 未删 |
| P2-3 全局状态管理 | P2 | 仍用 set/get |
| P2-4 整理调试脚本 | P2 | 未整理 |
| P2-5 SSE 心跳重连 | P2 | 未实现 |
| P2-6 前端消息 ID UUID | P2 | 仍用 Date.now |
| P2-7 ERROR_STATUS_CODE 映射 | P2 | 未实现 |
| P2-8 Health 接口探测 | P2 | 仍静态返回 |
| P2-9 get_conversation @_db_retry | P2 | 读操作未加 |
| P2-10 SSE 解析 event: 字段 | P2 | 未实现 |
| P2-13 RAG top_k 动态调整 | P2 | 未实现 |

### 5.3 不修复（6 项，设计决策）

| 编号 | 问题 | 理由 |
|------|------|------|
| 第一轮 B4/B13 | 非 Agent 模式 | 架构选择，不是缺陷 |
| 第一轮 A010 | Prompt 模板外部化 | 7 个 prompt 规模，外部化增加不必要的复杂度 |
| 第一轮 B14 | 单知识库硬编码 | 设计文档 §1.3 明确非目标 |
| 第一轮 B15 | 无 user_id | 设计文档 §1.3 明确非目标 |
| 第二轮 S-002 | nodes.py 拆分 | 节点逻辑内聚，拆分收益不大 |
| 第二轮 AI-004 | Prompt 外部化 | 与第一轮 A010 相同 |

---

## 六、待确认事项（需用户决策，不猜测）

1. **P0-1 API 密钥泄露**是否已轮换 + git 历史是否已清理？（最高优先级安全项）
2. **P1-7 Chunk 策略**：当前已有 `chunk_size=512, chunk_overlap=50`，是否需要改用 `MarkdownNodeParser` 替代默认 `SentenceSplitter`？是否需要删除现有 Chroma 持久化数据重建索引？
3. **依赖声明不全**：`pyproject.toml` 缺少 `tiktoken`、`sentence-transformers`、`torch` 三个实际使用的依赖声明，是否需要补全？
4. **依赖锁定**：是否引入 `uv` 或 `pip-tools` 锁定版本？（LangChain 生态破坏性更新频繁）
5. **可观测性增强**：是否引入 metrics/tracing？health 接口是否升级为真实探测（P2-8）？
6. **前端工程化**：是否处理 HelloWorld.vue 删除、消息 ID UUID、SSE 心跳等 P2 项？
7. **未读文件**：`ChatView.vue`/`App.vue`/`router/index.ts`/`README.md`/`.env.example`/单元测试实现细节——是否需要进一步阅读以确认前端视图层和测试质量？
