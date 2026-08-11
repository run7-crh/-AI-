# 学AI必备助手 -- 基于 Self-RAG 的知识库 Agent 系统

个人 AI 学习知识库 + 求职作品项目。解决个人学习笔记检索困难问题，同时作为 RAG/Agent 技术栈的实践作品。

---

## 项目背景

**为什么做这个项目**

- 个人 Obsidian 笔记积累到 20 篇后，需要智能检索和问答能力
- 系统学习 RAG、Agent、LangGraph 等技术，需要一个完整项目验证理解
- 作为求职作品，展示从 0 到 1 的 AI 应用开发能力

**解决什么问题**

- 传统关键词搜索无法理解语义，检索准确率低
- 笔记间的关联关系难以发现（如 RAG、微调、幻觉之间的联系）
- 需要区分"知识库已有内容"和"需要联网搜索的时效性信息"

---

## 技术架构

### 整体架构（LangGraph 节点拓扑）

```
                              START
                                |
                                v
                         [rewrite_query]  (问题改写，容错退回原 query)
                                |
                                v
                       [decompose_question]  (意图分类 + 问题分解)
                                |
              ┌─────────────────┼─────────────────┐
              |                 |                 |
        is_chitchat=true  needs_decomp=true     else
              |                 |                 |
              v                 v                 v
       [chitchat_node]  [multi_step_reason]  [judge_relevance]
              |                 |              (轻量检索短路)
              |                 |                 |
              |                 |          is_relevant?
              |                 |          ┌──────┴──────┐
              |                 |          v true        v false
              |                 |   [rag_retrieve]   [web_search]
              |                 |          |              |
              |                 |          v              |
              |                 |  [rag_quality_eval]     |
              |                 |   (reranker 阈值短路)   |
              |                 |          |              |
              |                 |   rag_quality_pass?     |
              |                 |   ┌──────┴──────┐      |
              |                 |   v true        v false |
              |                 | [generate_local]  |     |
              |                 |        |          |     |
              |                 |        |    [query_corrector] (CRAG 回路)
              |                 |        |          |     |
              |                 |        |          v     |
              |                 |        |   [rag_retrieve] (重试)
              |                 |        |          |     |
              |                 |        |     (仍失败?)──┘
              |                 |        |          |
              └────────────────┴────────┴──────────┘
                                |
                                v
                   [combined_quality_check]
                   (一次 LLM 同时评估幻觉 + 质量)
                                |
                   not halluc. AND quality_pass?
                   ┌────────────┴────────────┐
                   v true                    v false
                  END              [quality_fail]
                                   (设 quality_warning,
                                    保留 final_answer)
                                        |
                                        v
                                       END
```

### 4 条执行路径

**路径 A: chitchat -- 闲聊快速通道**

```
rewrite_query -> decompose_question(is_chitchat=true) -> chitchat_node -> END
```

最快路径，跳过所有质量检查。用于"你好""谢谢"等寒暄。

**路径 B: local -- 本地知识库检索生成**

```
rewrite_query -> decompose_question(else) -> judge_relevance(true) -> rag_retrieve
-> rag_quality_eval(pass) -> generate_local -> combined_quality_check(pass) -> END
```

理想路径，知识库内容足够回答问题。

**路径 C: online -- 联网搜索生成**

```
rewrite_query -> decompose_question(else) -> judge_relevance(false) -> web_search
-> generate_online -> combined_quality_check(pass) -> END
```

问题与知识库无关（如"2026 年最新 RAG 框架""今天 A 股表现"），或本地检索质量差且 CRAG 纠正失败。

**路径 D: decomposition -- 多步分解推理**

```
rewrite_query -> decompose_question(needs_decomposition=true) -> multi_step_reason
-> combined_quality_check(pass) -> END
```

用于对比类问题（"RAG 和 Fine-tuning 的区别"）或并列子问题（"A、B、C 分别是什么"）。

### CRAG 纠正回路

当 `rag_quality_eval` 失败时，不直接放弃走 `web_search`，而是先通过 `query_corrector` 节点二次改写查询，再重试一次检索。

- `correction_count` 上限 1 次，第二次仍失败才走 `web_search`
- `query_corrector` 职责不同于首次 `rewrite_query`：解决"检索方向错误"，回传失败原因给 LLM 帮助纠正

### 质量评估机制

**reranker 两级短路**

1. `judge_relevance` 轻量检索短路：`top_k=1` reranker 分数 >= 0.5 直接判 `relevant=true`，跳过 LLM
2. `rag_quality_eval` reranker 分数阈值短路：
   - `avg_score > 0.7` -> 直接通过
   - `avg_score < 0.3` -> 直接不通过
   - `0.3 <= avg_score <= 0.7` -> 灰色地带，调 LLM 精细判断

**LLM 合并质量评估**

`combined_quality_check` 一次 LLM 调用同时评估幻觉和答案质量，每次请求 LLM 调用从 6 次降到 5 次。

- `source` 按 `route_path` 取对应源材料（`online` -> `web_search_result`，`local/decomposition` -> `retrieval_result`）
- `chitchat` 不走此节点（直接 `END`）

---

## 核心特性

- **Corrective RAG 查询纠正**：检索失败后二次改写查询重试，`correction_count` 上限 1 次防死循环
- **BGE-reranker-v2-m3 + GPU 加速**：本地 `sentence-transformers CrossEncoder`，`main.py` lifespan 预热 2GB 模型
- **检索质量两级评估短路**：reranker 分数阈值 + LLM 灰色地带判断，省 LLM 调用
- **合并质量评估**：幻觉检测 + 答案质量一次 LLM 调用，`source` 按 `route_path` 动态取
- **全链路 query_log 日志**：`asyncio.shield` 保护写入，客户端断开也不丢数据
- **用户反馈闭环**：`PUT /api/feedback` upsert 语义，防止重复提交

---

## 技术栈

### 后端

- **框架**：FastAPI + sse-starlette + slowapi（API 限速）
- **LLM 编排**：LangGraph（StateGraph + `astream_events` v2）
- **LLM 客户端**：langchain-openai（ChatOpenAI，OpenAI 兼容协议调 DeepSeek）
- **RAG 框架**：LlamaIndex（VectorStoreIndex + VectorIndexRetriever）
- **向量库**：Chroma（PersistentClient 本地文件）
- **Embedding**：本地 `BAAI/bge-large-zh-v1.5`（dim=1024）
- **Reranker**：本地 `BAAI/bge-reranker-v2-m3`（sentence-transformers CrossEncoder，GPU 加速）
- **联网搜索**：tavily-python
- **LLM**：DeepSeek 官方 API（`deepseek-chat` + `deepseek-reasoner`）
- **重试**：tenacity（`@retry(3, 指数退避)`）
- **数据校验**：pydantic v2 + pydantic-settings
- **数据库**：SQLite + aiosqlite
- **Markdown 解析**：python-frontmatter（Obsidian frontmatter）
- **token 计数**：tiktoken（`cl100k_base`）

### 前端

- **框架**：Vue 3（Composition API + `<script setup>`）
- **状态管理**：Pinia（setup-style store）
- **路由**：vue-router
- **构建**：Vite + `@vitejs/plugin-vue`
- **类型**：TypeScript + `vue-tsc`
- **样式**：Tailwind CSS（无组件库）
- **Markdown 渲染**：markdown-it + highlight.js
- **图标**：lucide-vue-next
- **测试**：vitest + `@vue/test-utils` + jsdom

### 模型

- **Flash 模型**：`deepseek-chat`（用于 `rewrite_query`、`decompose_question`、`combined_quality_check`）
- **Pro Chat 模型**：`deepseek-chat`（用于 `generate_local`、`generate_online`、`chitchat_node`）
- **Pro Reason 模型**：`deepseek-reasoner`（用于 `multi_step_reason`）

### 数据库

- **会话存储**：SQLite（`conversations` + `messages` 两张表）
- **向量存储**：Chroma 本地持久化
- **日志存储**：SQLite（`query_log` + `feedback` 表）

---

## 快速开始

### 环境要求

- **Python**：>= 3.11
- **Node.js**：>= 18（推荐 20+）
- **CUDA**（可选，GPU 加速 Reranker）：推荐 12.x，PyTorch 2.6.0+cu124

### 后端启动步骤

```bash
cd backend

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -e .

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key

# 启动服务（默认端口 8000）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

首次启动会自动构建 Chroma 索引（`chunk_size=512, chunk_overlap=50`），Reranker 模型会在 lifespan 中预热。

### 前端启动步骤

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器（默认端口 5173）
npm run dev
```

访问 `http://localhost:5173`，Vite 会自动代理 `/api/*` 到后端 8000 端口。

### .env 配置项说明

参考 `.env.example`：

```bash
# DeepSeek API（必填）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# Tavily Search（必填，联网搜索用）
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx

# 知识库目录（可选，默认 <项目根>/data/raw）
# KB_DATA_DIR=./data/raw

# Chroma 持久化目录与 collection 名（可选，默认值见 config.py）
# CHROMA_PERSIST_DIR=backend/data/chroma
# CHROMA_COLLECTION_NAME=obsidian_kb
```

**不要泄露真实 API Key**。`.env` 已在 `.gitignore` 中。

---

## 项目结构

```
Agent/
├── backend/                    # 后端
│   ├── app/                    # FastAPI 应用
│   │   ├── api/                # API 路由（chat, conversations, index, health）
│   │   ├── graph/              # LangGraph 编排层（nodes, builder, prompts, state, tools）
│   │   ├── models/             # 数据模型（schemas, query_log）
│   │   ├── services/           # 服务层（conversation_store, query_log_service）
│   │   ├── config.py           # 配置（pydantic-settings，从 .env 读）
│   │   ├── main.py             # FastAPI 入口（lifespan，Reranker 预热）
│   │   └── extensions.py       # 扩展（slowapi Limiter 单例）
│   ├── data/                   # 数据目录
│   │   ├── raw/                # 原始 Obsidian 笔记（20 篇）
│   │   └── processed/          # 处理后笔记（去重清理）
│   ├── eval/                   # 评估体系
│   │   ├── dataset.json        # 评估集（99 条，5 类问题）
│   │   ├── reports/            # 评估报告（JSON）
│   │   └── run_eval.py         # 评估脚本
│   ├── rag/                    # RAG 层
│   │   ├── embedding.py        # Embedding 配置（本地 BGE）
│   │   ├── indexer.py          # Chroma 索引构建
│   │   ├── retriever.py        # 向量检索 + Reranking（GPU 加速）
│   │   └── readers.py          # Obsidian Markdown 读取器
│   ├── tests/                  # 测试
│   ├── pyproject.toml          # Python 依赖
│   └── .env.example            # 环境变量示例
├── frontend/                   # 前端
│   ├── src/
│   │   ├── api/                # API 客户端（chat.ts, conversations.ts）
│   │   ├── components/         # 组件
│   │   ├── stores/             # Pinia Store（chat.ts）
│   │   ├── views/              # 视图（ChatView.vue）
│   │   ├── types/              # TypeScript 类型
│   │   └── App.vue             # 根组件
│   ├── package.json            # Node 依赖
│   └── vite.config.ts          # Vite 配置
├── PROJECT_CONTEXT.md          # 项目上下文文档
└── README.md                   # 本文件
```

---

## 评估体系

### 评估集规模

99 条测试问题，5 类问题分布：

| 类别 | 数量 | 说明 |
|------|------|------|
| `knowledge_hit` | 40 | 知识库已有内容（如"什么是 RAG"） |
| `knowledge_missing` | 19 | 知识库缺失，需联网（如"2026 最新框架"） |
| `multi_hop` | 20 | 多步推理（如"A 和 B 的区别"） |
| `routing_test` | 10 | 路由判断（闲聊、关联问题） |
| `hallucination_test` | 10 | 幻觉测试（知识库未提及的细节） |

难度分布：easy 27 条，medium 42 条，hard 30 条。

### 评估指标定义

1. **route_accuracy**：路由准确率（实际路径是否在 `acceptable_routes` 中）
2. **answer_relevance**：答案相关性（答案是否包含 `expected_answer_keywords`）
3. **source_correctness**：引用来源正确率（答案中的 `[来源：XXX]` 是否匹配 `expected_source`）
4. **retrieval_success_rate**：检索成功率（`retrieved_doc_ids` 是否包含 `expected_source`）
5. **hallucination_count**：幻觉数量（答案包含知识库未提及的事实）
6. **latency_ms**：响应延迟（毫秒）

### 2 轮评估对比

| 指标 | 第 1 轮（基线） | 第 2 轮（优化后） |
|------|----------------|------------------|
| route_accuracy | 39.4% (39/99) | 93.9% (93/99) |
| answer_relevance | 100.0% (60/60) | 100.0% (60/60) |
| source_correctness | 88.1% (59/67) | 85.9% (55/64) |
| retrieval_success_rate | 100.0% (25/25) | 100.0% (65/65) |
| hallucination_count | 3 | 0 |
| 平均延迟 (ms) | 37,416 | 18,197 |

**第 1 轮时间**：2026-08-10

**第 2 轮时间**：2026-08-11

**关键改进**：

第 1 轮基线暴露出路由策略是最大瓶颈：`knowledge_hit` 类 40 题中 28 题被误判为 `decomposition`，`hallucination_test` 10 题全部路由失败，`knowledge_missing` 也有约 1/3 未正确走 `online`。第 2 轮针对以上问题做了以下优化并验证：

1. **收紧 `decompose_question` 判定**：降低对单点知识问答和简单对比问题的分解触发阈值，让 `knowledge_hit` 类优先走 `local`。该类路由准确率从 30.0% 提升至 97.5%。
2. **增强 `judge_relevance` 对幻觉题和知识缺失题的识别**：加入对"细节不存在于知识库"和"知识库未覆盖"的显式判断，`hallucination_test` 路由准确率从 0% 提升至 100%，`knowledge_missing` 从 68.4% 提升至 100%。
3. **优化路由策略与节点调用**：减少不必要的 DeepSeek API 调用路径，平均延迟从 37,416 ms 降至 18,197 ms（P50 从 22,445 ms 降至 13,588 ms），最大延迟从 186,335 ms 降至 97,679 ms，端到端响应明显变快。

**仍存在的短板**：

- `routing_test` 路由准确率 70.0%，6 个失败案例中有 4 个是闲聊/关联问题被误判为 `online`（q090、q091、q093）或多跳问题被误判为 `online`（q060、q063），说明对弱语义/无检索需求 query 的识别仍需细化。
- `source_correctness` 从 88.1% 微降至 85.9%，主要受 `multi_hop` 类影响（77.8%），多跳答案的引用标注与预期文档匹配还有优化空间。

---

## 已知局限

1. **依赖声明不全**：`pyproject.toml` 缺少 `tiktoken`、`sentence-transformers`、`torch` 三个实际使用的依赖声明。运行时能工作是因为这些包被其他依赖间接安装，但全新环境部署会失败。

2. **Health 接口未真实探测**：`GET /api/health` 仍只返回静态字段，未探测数据库和向量库可达性。生产环境需要升级为真实健康检查。

3. **前端工程化待完善**：消息 ID 仍用 `Date.now()`（高并发可能冲突），SSE 无心跳重连机制，`HelloWorld.vue` 未删除。

4. **无认证和权限隔离**：API 无认证机制，CORS 写死 `localhost`。设计文档明确"不做用户系统/权限隔离"，但部署到公网需要补充。

5. **单知识库硬编码**：当前只支持单个知识库目录，多知识库场景需要扩展。设计文档明确此为"非目标"。
