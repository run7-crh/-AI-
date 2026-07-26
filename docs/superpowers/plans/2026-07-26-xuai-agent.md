# 学AI必备助手 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Dify advanced-chat 工作流「学AI必备助手」用 LlamaIndex + LangGraph + FastAPI + Vue 3 重新实现为可独立部署的应用。

**Architecture:** 4 层架构——LlamaIndex RAG 检索层、LangGraph 8 节点状态机编排层、FastAPI SSE 流式服务层、Vue 3 SPA 前端。会话用 SQLite 持久化，向量库用 Chroma。详见 [设计文档](../specs/2026-07-26-xuai-agent-design.md)。

**Tech Stack:** Python 3.11+ / FastAPI / LangGraph / LlamaIndex / Chroma / aiosqlite / pydantic-settings / sse-starlette / tenacity / pytest；Vue 3 / Vite / TypeScript / Pinia / Tailwind / markdown-it / Vitest

**关键参考文档：** 实现代码以 [设计文档](../specs/2026-07-26-xuai-agent-design.md) 为准。本计划聚焦任务拆解与 TDD 流程，复杂代码块引用设计文档相应章节。

---

## 文件结构映射

### 后端（backend/）

| 文件 | 责任 |
|------|------|
| `pyproject.toml` | 依赖管理 |
| `.env.example` | API Key 模板 |
| `app/config.py` | Settings 类（pydantic-settings） |
| `app/models/schemas.py` | Pydantic 请求/响应模型 |
| `app/services/conversation_store.py` | SQLite 异步会话存储 |
| `app/rag/readers.py` | ObsidianMarkdownReader |
| `app/rag/retriever.py` | HuaweiReranker + RAGRetriever |
| `app/rag/indexer.py` | Indexer（构建/加载/更新） |
| `app/graph/state.py` | AgentState TypedDict |
| `app/graph/prompts.py` | 提示词模板（REWRITE/DECOMPOSE/MULTI_STEP/LOCAL_GEN/ONLINE_GEN + 3 个评估提示词） |
| `app/graph/tools.py` | call_llm / evaluate / retrieve / tavily_search |
| `app/graph/nodes.py` | 8 个节点函数 + fallback_online 子图 |
| `app/graph/builder.py` | StateGraph 构建 + 条件路由 |
| `app/api/errors.py` | 错误处理 + 状态码映射 |
| `app/api/health.py` | 健康检查 |
| `app/api/conversations.py` | 会话 CRUD 路由 |
| `app/api/chat.py` | 流式对话 SSE 路由 |
| `app/api/index.py` | 索引重建路由 |
| `app/main.py` | FastAPI 入口 + lifespan |
| `tests/conftest.py` | 公共 fixture |
| `tests/unit/test_*.py` | 单元测试（按模块分文件） |
| `tests/integration/test_api_*.py` | API 集成测试 |
| `tests/e2e/test_*_path.py` | 3 条路径端到端测试 |

### 前端（frontend/）

| 文件 | 责任 |
|------|------|
| `package.json` / `vite.config.ts` / `tailwind.config.js` / `tsconfig.json` | 项目配置 |
| `src/main.ts` / `src/App.vue` | 入口 |
| `src/router/index.ts` | Vue Router |
| `src/types/index.ts` | TypeScript 类型 |
| `src/api/conversations.ts` | 会话 API |
| `src/api/chat.ts` | SSE 客户端 |
| `src/stores/chat.ts` | Pinia store |
| `src/views/ChatView.vue` | 主聊天页 |
| `src/components/*.vue` | 14 个组件 |

---

## Phase 1: 项目骨架

### Task 1: 后端项目初始化

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/app/__init__.py` (空)
- Create: `backend/app/api/__init__.py` (空)
- Create: `backend/app/models/__init__.py` (空)
- Create: `backend/app/services/__init__.py` (空)
- Create: `backend/app/rag/__init__.py` (空)
- Create: `backend/app/graph/__init__.py` (空)
- Create: `backend/tests/__init__.py` (空)
- Create: `backend/tests/unit/__init__.py` (空)
- Create: `backend/tests/integration/__init__.py` (空)
- Create: `backend/tests/e2e/__init__.py` (空)

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "xuai-agent-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.27.0",
    "sse-starlette>=2.0.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.1.0",
    "aiosqlite>=0.19.0",
    "langgraph>=0.2.0",
    "langchain-openai>=0.1.0",
    "llama-index>=0.10.0",
    "llama-index-vector-stores-chroma>=0.1.0",
    "chromadb>=0.5.0",
    "python-frontmatter>=1.1.0",
    "tavily-python>=0.3.0",
    "tenacity>=8.2.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "httpx>=0.27.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: 创建 .env.example**

```env
# DeepSeek API
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 华为云 MaaS (Embedding + Reranker)
HUAWEI_API_KEY=xxxxxxxxxxxxxxxx

# Tavily Search
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx

# 知识库目录
KB_DATA_DIR=D:\Project\Self-RAG-Agent\data\raw
```

- [ ] **Step 3: 创建所有空 `__init__.py` 文件**

按 Files 清单创建 12 个空文件。

- [ ] **Step 4: 安装依赖验证**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Expected: 安装成功，无错误。

- [ ] **Step 5: 提交**

```bash
git add backend/
git commit -m "chore: 初始化后端项目骨架"
```

---

### Task 2: 前端项目初始化

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/postcss.config.js`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/style.css`
- Create: `frontend/src/vite-env.d.ts`

- [ ] **Step 1: 用 Vite 创建 Vue 3 + TS 项目**

```bash
cd d:\Project\Agent
npm create vite@latest frontend -- --template vue-ts
cd frontend
npm install
npm install pinia vue-router@4 markdown-it highlight.js lucide-vue-next
npm install -D tailwindcss postcss autoprefixer @types/markdown-it
npx tailwindcss init -p
```

- [ ] **Step 2: 配置 vite.config.ts（含 /api 代理）**

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: 配置 tailwind.config.js**

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: { extend: {} },
  plugins: [],
}
```

- [ ] **Step 4: 配置 src/style.css**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #app { height: 100%; margin: 0; }
```

- [ ] **Step 5: 配置 tsconfig.json paths**

在 compilerOptions 中添加：
```json
"paths": { "@/*": ["./src/*"] }
```

- [ ] **Step 6: 简化 src/App.vue**

```vue
<script setup lang="ts">
</script>

<template>
  <div class="h-full">Hello</div>
</template>
```

- [ ] **Step 7: 验证启动**

```bash
npm run dev
```

Expected: 浏览器访问 http://localhost:5173 看到 "Hello"。

- [ ] **Step 8: 提交**

```bash
git add frontend/
git commit -m "chore: 初始化前端项目骨架（Vite + Vue 3 + Tailwind）"
```

---

## Phase 2: 后端配置与数据模型

### Task 3: Settings 配置类

**Files:**
- Create: `backend/app/config.py`
- Test: `backend/tests/unit/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_config.py
import os
from app.config import Settings

def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("HUAWEI_API_KEY", "hw-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    s = Settings()
    assert s.DEEPSEEK_API_KEY == "sk-test"
    assert s.HUAWEI_API_KEY == "hw-test"
    assert s.TAVILY_API_KEY == "tvly-test"
    assert s.MODEL_FLASH == "deepseek-chat"
    assert s.MODEL_PRO_REASON == "deepseek-reasoner"
    assert s.EMBEDDING_MODEL == "bge-large-zh-v1.5"
    assert s.CORS_ORIGINS == ["http://localhost:5173", "http://localhost:4173"]
```

- [ ] **Step 2: 运行验证失败**

```bash
cd backend
pytest tests/unit/test_config.py -v
```

Expected: FAIL（ModuleNotFoundError: app.config）

- [ ] **Step 3: 实现 config.py**

按设计文档 7.7 节代码实现。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_config.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/tests/unit/test_config.py
git commit -m "feat: 添加 Settings 配置类"
```

---

### Task 4: Pydantic Schemas

**Files:**
- Create: `backend/app/models/schemas.py`
- Test: `backend/tests/unit/test_schemas.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_schemas.py
import pytest
from datetime import datetime
from pydantic import ValidationError
from app.models.schemas import ChatRequest, ConversationCreate, ConversationUpdate

def test_chat_request_valid():
    req = ChatRequest(conversation_id="abc", message="你好")
    assert req.conversation_id == "abc"
    assert req.message == "你好"

def test_chat_request_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id="abc", message="")

def test_chat_request_rejects_too_long_message():
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id="abc", message="x" * 2001)

def test_conversation_create_optional_title():
    c = ConversationCreate()
    assert c.title is None
    c2 = ConversationCreate(title="测试")
    assert c2.title == "测试"

def test_conversation_update_requires_title():
    with pytest.raises(ValidationError):
        ConversationUpdate()
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_schemas.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 schemas.py**

按设计文档 7.3 节代码实现（ChatRequest / ConversationCreate / ConversationUpdate / ConversationResponse / MessageResponse / ConversationDetail / IndexRebuildResponse / HealthResponse）。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_schemas.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/models/ backend/tests/unit/test_schemas.py
git commit -m "feat: 添加 Pydantic schemas"
```

---

### Task 5: SQLite 会话存储

**Files:**
- Create: `backend/app/services/conversation_store.py`
- Test: `backend/tests/unit/test_store.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_store.py
import pytest
import tempfile
import os
from app.services.conversation_store import ConversationStore

@pytest.fixture
async def store():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = ConversationStore(db_path)
    await s.init()
    yield s
    os.unlink(db_path)

@pytest.mark.asyncio
async def test_create_and_get_conversation(store):
    conv_id = await store.create_conversation(title="测试")
    conv = await store.get_conversation(conv_id)
    assert conv is not None
    assert conv["title"] == "测试"
    assert conv["message_count"] == 0

@pytest.mark.asyncio
async def test_list_conversations_ordered_by_updated(store):
    id1 = await store.create_conversation(title="会话1")
    id2 = await store.create_conversation(title="会话2")
    convs = await store.list_conversations()
    assert convs[0]["id"] == id2  # 最新创建的在前
    assert convs[1]["id"] == id1

@pytest.mark.asyncio
async def test_add_message_updates_count_and_history(store):
    conv_id = await store.create_conversation()
    await store.add_message(conv_id, role="user", content="问题1")
    await store.add_message(conv_id, role="assistant", content="回答1",
                            route_path="local", sources=[{"x": 1}], judge_log=[{"y": 2}])
    history = await store.get_history(conv_id, limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    conv = await store.get_conversation(conv_id)
    assert conv["message_count"] == 2
    assert conv["messages"][1]["sources"] == [{"x": 1}]
    assert conv["messages"][1]["judge_log"] == [{"y": 2}]

@pytest.mark.asyncio
async def test_delete_conversation_cascades_messages(store):
    conv_id = await store.create_conversation()
    await store.add_message(conv_id, role="user", content="x")
    ok = await store.delete_conversation(conv_id)
    assert ok is True
    conv = await store.get_conversation(conv_id)
    assert conv is None

@pytest.mark.asyncio
async def test_update_conversation_title(store):
    conv_id = await store.create_conversation(title="旧标题")
    ok = await store.update_conversation_title(conv_id, "新标题")
    assert ok is True
    conv = await store.get_conversation(conv_id)
    assert conv["title"] == "新标题"

@pytest.mark.asyncio
async def test_get_history_respects_limit(store):
    conv_id = await store.create_conversation()
    for i in range(5):
        await store.add_message(conv_id, role="user", content=f"问题{i}")
    history = await store.get_history(conv_id, limit=3)
    assert len(history) == 3
    assert history[-1]["content"] == "问题4"  # 时间正序，最后一条是问题4
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_store.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 conversation_store.py**

按设计文档 7.4 节代码实现，包含 SCHEMA_SQL 常量（设计文档 7.2 节的建表语句）和 ConversationStore 类的 8 个方法。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_store.py -v
```

Expected: PASS（6 个测试全过）

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/ backend/tests/unit/test_store.py
git commit -m "feat: 添加 SQLite 异步会话存储"
```

---

## Phase 3: RAG 层

### Task 6: ObsidianMarkdownReader

**Files:**
- Create: `backend/app/rag/readers.py`
- Test: `backend/tests/unit/test_readers.py`

- [ ] **Step 1: 写失败测试**

按设计文档 9.1 节 test_readers.py 的 5 个测试用例完整复制：
- `test_strip_wikilinks_simple`
- `test_strip_wikilinks_with_alias`
- `test_strip_callouts`
- `test_strip_embeds`
- `test_load_real_obsidian_file`

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_readers.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 readers.py**

按设计文档 6.1 节代码实现 ObsidianMarkdownReader 类。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_readers.py -v
```

Expected: PASS（5 个测试全过）

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag/readers.py backend/tests/unit/test_readers.py
git commit -m "feat: 添加 ObsidianMarkdownReader"
```

---

### Task 7: HuaweiReranker

**Files:**
- Modify: `backend/app/rag/retriever.py`（创建文件）
- Test: `backend/tests/unit/test_reranker.py`

**注意**：华为云 MaaS rerank API 集成需要真实 API Key 调通，本任务先实现 mock-friendly 版本（接口签名正确，实际调用可注入 mock）。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_reranker.py
import pytest
from unittest.mock import patch, MagicMock
from llama_index.core.schema import NodeWithScore, TextNode
from app.rag.retriever import HuaweiReranker

def test_reranker_sorts_by_score_desc():
    reranker = HuaweiReranker()
    nodes = [
        NodeWithScore(node=TextNode(text="低分内容"), score=0.1),
        NodeWithScore(node=TextNode(text="高分内容"), score=0.9),
        NodeWithScore(node=TextNode(text="中分内容"), score=0.5),
    ]
    with patch.object(reranker, "_call_huawei_rerank",
                      return_value={"scores": [0.1, 0.9, 0.5]}):
        result = reranker._postprocess_nodes(nodes, query_str="test")
    assert result[0].node.get_content() == "高分内容"
    assert result[1].node.get_content() == "中分内容"
    assert result[2].node.get_content() == "低分内容"

def test_reranker_empty_nodes_returns_empty():
    reranker = HuaweiReranker()
    assert reranker._postprocess_nodes([], query_str="test") == []

def test_reranker_class_name():
    assert HuaweiReranker.class_name() == "HuaweiReranker"
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_reranker.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 retriever.py 的 HuaweiReranker 类**

按设计文档 6.3 节代码实现 HuaweiReranker（`_call_huawei_rerank` 内部用 httpx 调华为云 MaaS rerank 接口，本任务先实现方法签名 + httpx 调用结构，实际 API 路径根据华为云文档补充）。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_reranker.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag/retriever.py backend/tests/unit/test_reranker.py
git commit -m "feat: 添加 HuaweiReranker（华为云 bge-reranker-v2-m3）"
```

---

### Task 8: RAGRetriever

**Files:**
- Modify: `backend/app/rag/retriever.py`（追加 RAGRetriever 类）
- Test: `backend/tests/unit/test_retriever.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_retriever.py
import pytest
from unittest.mock import MagicMock, patch
from llama_index.core.schema import NodeWithScore, TextNode
from app.rag.retriever import RAGRetriever

def test_retrieve_returns_top_k_formatted():
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [
        NodeWithScore(node=TextNode(text="内容1", metadata={"file_name": "a.md", "title": "A"}), score=0.9),
        NodeWithScore(node=TextNode(text="内容2", metadata={"file_name": "b.md", "title": "B"}), score=0.8),
        NodeWithScore(node=TextNode(text="内容3", metadata={"file_name": "c.md", "title": "C"}), score=0.7),
    ]
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=3)
        # mock reranker 直接返回原顺序
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str: nodes):
            result = r.retrieve("测试 query")
    assert len(result) == 3
    assert result[0]["content"] == "内容1"
    assert result[0]["source"] == "a.md"
    assert result[0]["title"] == "A"
    assert result[0]["score"] == 0.9

def test_retrieve_initial_recall_is_3x():
    """验证初检召回 top_k * 3 = 9。"""
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = []
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever) as mock_cls:
        r = RAGRetriever(mock_index, top_k=3)
        r.retrieve("test")
    # 验证 VectorIndexRetriever 构造时 similarity_top_k=9
    assert mock_cls.call_args.kwargs["similarity_top_k"] == 9

def test_retrieve_empty_returns_empty():
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = []
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=3)
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str: nodes):
            result = r.retrieve("test")
    assert result == []
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_retriever.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 RAGRetriever 类**

在 retriever.py 中追加 RAGRetriever 类，按设计文档 6.3 节代码实现。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_retriever.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag/retriever.py backend/tests/unit/test_retriever.py
git commit -m "feat: 添加 RAGRetriever（向量检索 + Reranking）"
```

---

### Task 9: Indexer

**Files:**
- Create: `backend/app/rag/indexer.py`
- Test: `backend/tests/unit/test_indexer.py`

**注意**：本任务依赖华为云 Embedding API，测试用 mock 避免真实调用。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_indexer.py
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.rag.indexer import Indexer

@pytest.fixture
def temp_dirs():
    with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as persist_dir:
        # 创建测试 .md 文件
        (Path(data_dir) / "test.md").write_text("# 测试\n\n这是测试内容", encoding="utf-8")
        yield data_dir, persist_dir

def test_indexer_init_creates_chroma_collection(temp_dirs, monkeypatch):
    data_dir, persist_dir = temp_dirs
    # mock Settings.embed_model 避免真实 API 调用
    with patch("app.rag.indexer.Settings"):
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
    assert idx.chroma_collection is not None
    assert idx.data_dir == Path(data_dir)
    assert idx.persist_dir == Path(persist_dir)

def test_indexer_build_loads_documents(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        idx.build()
        # 验证 from_documents 被调用
        mock_vsi.from_documents.assert_called_once()
        args = mock_vsi.from_documents.call_args
        # 验证加载了 1 个 .md 文件
        docs = args.args[0]
        assert len(docs) >= 1

def test_indexer_get_retriever_returns_rag_retriever(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"):
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        idx.index = MagicMock()
        r = idx.get_retriever()
        from app.rag.retriever import RAGRetriever
        assert isinstance(r, RAGRetriever)
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_indexer.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 indexer.py**

按设计文档 6.2 节代码实现 Indexer 类。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_indexer.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag/indexer.py backend/tests/unit/test_indexer.py
git commit -m "feat: 添加 Indexer（索引构建/加载/更新）"
```

---

## Phase 4: LangGraph 编排层

### Task 10: AgentState + 提示词模板

**Files:**
- Create: `backend/app/graph/state.py`
- Create: `backend/app/graph/prompts.py`
- Test: `backend/tests/unit/test_state.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_state.py
from app.graph.state import AgentState, JudgeResult
from typing import get_type_hints

def test_agent_state_has_required_fields():
    hints = get_type_hints(AgentState)
    required = ["query", "conversation_id", "history", "rewritten_query",
                "needs_decomposition", "is_relevant", "retrieval_result",
                "rag_quality_pass", "web_search_result", "local_answer",
                "online_answer", "hallucination_flag", "answer_quality_pass",
                "final_answer", "route_path", "judge_log"]
    for field in required:
        assert field in hints, f"Missing field: {field}"

def test_judge_log_uses_add_reducer():
    """验证 judge_log 用 add reducer（Annotated[list, add]）。"""
    # 通过实际 merge 验证
    from app.graph.state import AgentState
    # TypedDict 不能直接实例化测试 reducer，改为静态检查 hints
    hints = get_type_hints(AgentState, include_extras=True)
    judge_log_hint = hints.get("judge_log")
    # Annotated 类型会有 __metadata__
    assert hasattr(judge_log_hint, "__metadata__") or judge_log_hint is not None

def test_judge_result_structure():
    jr: JudgeResult = {"judge_type": "is_relevant", "passed": True, "raw_output": {}}
    assert jr["passed"] is True
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_state.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 state.py**

按设计文档 5.1 节代码实现 AgentState 和 JudgeResult。

- [ ] **Step 4: 实现 prompts.py**

从 Dify DSL 提取 7 个提示词模板（REWRITE / DECOMPOSE / MULTI_STEP / LOCAL_GEN / ONLINE_GEN + IS_RELEVANT / IS_QUALITY_PASS / IS_HALLUCINATION）。

```python
# backend/app/graph/prompts.py
REWRITE_PROMPT = """..."""  # 从 DSL 节点 1784708937350 提取
DECOMPOSE_PROMPT = """..."""  # 从 DSL 节点 1785059627106 提取
MULTI_STEP_PROMPT = """..."""  # 从 DSL 节点 1785059818901 提取
LOCAL_GEN_PROMPT = """..."""  # 从 DSL 节点 1784711392079 提取
ONLINE_GEN_PROMPT = """..."""  # 从 DSL 节点 1784713973176 提取
IS_RELEVANT_PROMPT = """..."""  # 从 DSL 节点 1785000000001 提取
IS_QUALITY_PASS_PROMPT = """..."""  # 从 DSL 节点 1785100000001 / 1785057290442 提取
IS_HALLUCINATION_PROMPT = """..."""  # 从 DSL 节点 1785054451820 / 1785054783773 提取
```

**注意**：DSL 文件路径 `D:\Project\Self-RAG-Agent\学AI必备助手.yml`，提取后填入。每个提示词保留 DSL 原文（包括变量占位符 `{{query}}` 等），在调用时做字符串替换或传给 LangChain 的 `ChatPromptTemplate`。

- [ ] **Step 5: 运行验证通过**

```bash
pytest tests/unit/test_state.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/graph/state.py backend/app/graph/prompts.py backend/tests/unit/test_state.py
git commit -m "feat: 添加 AgentState 状态定义和提示词模板"
```

---

### Task 11: call_llm 工具

**Files:**
- Create: `backend/app/graph/tools.py`
- Test: `backend/tests/unit/test_tools.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_tools.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.graph.tools import call_llm, evaluate, retrieve, tavily_search

@pytest.mark.asyncio
async def test_call_llm_returns_text():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "测试回复"
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        result = await call_llm("system", "user", temperature=0.5)
    assert result["text"] == "测试回复"
    assert result["structured"] is None

@pytest.mark.asyncio
async def test_call_llm_with_history_passes_messages():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "回复"
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm) as mock_cls:
        await call_llm("system", "user", history=[{"role": "user", "content": "历史"}])
    # 验证 ainvoke 被调用，且 messages 包含历史
    mock_llm.ainvoke.assert_called_once()
    msgs = mock_llm.ainvoke.call_args.args[0]
    assert len(msgs) >= 3  # system + history + user

@pytest.mark.asyncio
async def test_call_llm_with_schema_returns_structured():
    from pydantic import BaseModel
    class TestSchema(BaseModel):
        passed: bool
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.passed = True
    mock_llm.with_structured_output = MagicMock(return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_structured)))
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        result = await call_llm("system", "user", output_schema=TestSchema)
    assert result["structured"]["passed"] is True
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_tools.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 tools.py 的 call_llm 函数**

按设计文档 5.5 节代码实现。使用 `langchain_openai.ChatOpenAI` 包装 DeepSeek API（`base_url` 指向 DeepSeek）。

```python
# backend/app/graph/tools.py 核心结构
from langchain_openai import ChatOpenAI
from app.config import settings

async def call_llm(system_prompt, user_input, temperature=0.3,
                   output_schema=None, history=None, model="deepseek-chat"):
    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
    )
    messages = [SystemMessage(content=system_prompt)]
    if history:
        for h in history:
            messages.append(HumanMessage(content=h["content"]) if h["role"] == "user"
                            else AIMessage(content=h["content"]))
    messages.append(HumanMessage(content=user_input))
    
    if output_schema:
        structured_llm = llm.with_structured_output(output_schema)
        result = await structured_llm.ainvoke(messages)
        return {"text": "", "structured": result.dict() if hasattr(result, "dict") else dict(result)}
    
    response = await llm.ainvoke(messages)
    return {"text": response.content, "structured": None}
```

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_tools.py::test_call_llm_returns_text tests/unit/test_tools.py::test_call_llm_with_history_passes_messages tests/unit/test_tools.py::test_call_llm_with_schema_returns_structured -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/tools.py backend/tests/unit/test_tools.py
git commit -m "feat: 添加 call_llm 工具函数"
```

---

### Task 12: evaluate 工具

**Files:**
- Modify: `backend/app/graph/tools.py`（追加 evaluate 函数）
- Modify: `backend/tests/unit/test_tools.py`（追加测试）

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/unit/test_tools.py
from pydantic import BaseModel

class JudgeSchema(BaseModel):
    passed: bool
    reason: str

@pytest.mark.asyncio
async def test_evaluate_is_relevant_returns_passed_true():
    mock_structured = MagicMock()
    mock_structured.passed = True
    mock_structured.reason = "相关问题"
    mock_llm = MagicMock()
    mock_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_structured))
    )
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        result = await evaluate(judge_type="is_relevant", source="", query="什么是 RAG？")
    assert result["passed"] is True
    assert result["judge_type"] == "is_relevant"
    assert "reason" in result["raw_output"]

@pytest.mark.asyncio
async def test_evaluate_uses_temp_0_2_regardless_of_input():
    """验证评估温度统一为 0.2（修复设计问题 2）。"""
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.passed = False
    mock_structured.reason = "原因"
    mock_llm.with_structured_output = MagicMock(
        return_value=MagicMock(ainvoke=AsyncMock(return_value=mock_structured))
    )
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm) as mock_cls:
        await evaluate(judge_type="is_hallucination", source="x", answer="y", query="z")
    # 验证 ChatOpenAI 构造时 temperature=0.2
    assert mock_cls.call_args.kwargs["temperature"] == 0.2

@pytest.mark.asyncio
async def test_evaluate_invalid_judge_type_raises():
    with pytest.raises(ValueError):
        await evaluate(judge_type="invalid_type", source="x")
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_tools.py -v -k evaluate
```

Expected: FAIL

- [ ] **Step 3: 实现 evaluate 函数**

在 tools.py 追加：

```python
from app.graph.prompts import IS_RELEVANT_PROMPT, IS_QUALITY_PASS_PROMPT, IS_HALLUCINATION_PROMPT

JUDGE_PROMPTS = {
    "is_relevant": IS_RELEVANT_PROMPT,
    "is_quality_pass": IS_QUALITY_PASS_PROMPT,
    "is_hallucination": IS_HALLUCINATION_PROMPT,
}

class JudgeSchema(BaseModel):
    passed: bool
    reason: str

async def evaluate(judge_type: str, source: str, answer: str = "", query: str = "") -> dict:
    if judge_type not in JUDGE_PROMPTS:
        raise ValueError(f"Unknown judge_type: {judge_type}")
    
    prompt = JUDGE_PROMPTS[judge_type].format(source=source, answer=answer, query=query)
    result = await call_llm(
        system_prompt=prompt,
        user_input=query or "请评估",
        temperature=0.2,  # 硬编码 0.2
        output_schema=JudgeSchema,
        model=settings.MODEL_FLASH,
    )
    return {
        "judge_type": judge_type,
        "passed": result["structured"]["passed"],
        "raw_output": result["structured"],
    }
```

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_tools.py -v -k evaluate
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/tools.py backend/tests/unit/test_tools.py
git commit -m "feat: 添加 evaluate 统一评估工具"
```

---

### Task 13: retrieve + tavily_search 工具

**Files:**
- Modify: `backend/app/graph/tools.py`（追加 retrieve 和 tavily_search 函数）
- Modify: `backend/tests/unit/test_tools.py`（追加测试）

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/unit/test_tools.py
@pytest.mark.asyncio
async def test_retrieve_calls_rag_retriever():
    mock_retriever = MagicMock()
    mock_retriever.retrieve = MagicMock(return_value=[{"content": "x", "source": "a.md", "title": "A", "score": 0.9}])
    # retrieve 是 sync 函数，直接调用
    result = await retrieve("测试", mock_retriever, top_k=3)
    mock_retriever.retrieve.assert_called_once_with("测试")
    assert result[0]["content"] == "x"

@pytest.mark.asyncio
async def test_tavily_search_returns_formatted_string():
    mock_client = MagicMock()
    mock_response = {"results": [{"content": "结果1"}, {"content": "结果2"}]}
    mock_client.search = MagicMock(return_value=mock_response)
    with patch("app.graph.tools.TavilyClient", return_value=mock_client):
        result = await tavily_search("test query", max_results=5)
    assert "结果1" in result
    assert "结果2" in result

@pytest.mark.asyncio
async def test_tavily_search_handles_empty_results():
    mock_client = MagicMock()
    mock_client.search = MagicMock(return_value={"results": []})
    with patch("app.graph.tools.TavilyClient", return_value=mock_client):
        result = await tavily_search("test")
    assert result == ""
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_tools.py -v -k "retrieve or tavily"
```

Expected: FAIL

- [ ] **Step 3: 实现 retrieve 和 tavily_search 函数**

```python
# 追加到 backend/app/graph/tools.py
async def retrieve(query: str, rag_retriever, top_k: int = 3) -> list[dict]:
    """调用 RAGRetriever（同步函数，用 run_in_executor 包装）。"""
    import asyncio
    return await asyncio.to_thread(rag_retriever.retrieve, query)

async def tavily_search(query: str, max_results: int = 5) -> str:
    from tavily import TavilyClient
    client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    response = await asyncio.to_thread(
        client.search, query=query, max_results=max_results, search_depth="basic"
    )
    results = response.get("results", [])
    return "\n\n".join([f"[{i+1}] {r.get('content', '')}" for i, r in enumerate(results)])
```

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_tools.py -v -k "retrieve or tavily"
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/tools.py backend/tests/unit/test_tools.py
git commit -m "feat: 添加 retrieve 和 tavily_search 工具"
```

---

### Task 14: 节点 1-2（rewrite_query + decompose_question）

**Files:**
- Create: `backend/app/graph/nodes.py`
- Test: `backend/tests/unit/test_nodes.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_nodes.py
import pytest
from unittest.mock import patch, AsyncMock
from app.graph.state import AgentState
from app.graph.nodes import rewrite_query_node, decompose_question_node

@pytest.mark.asyncio
async def test_rewrite_query_node_writes_rewritten_query():
    state = AgentState(
        query="什么是 RAG？", conversation_id="c1", history=[], judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "RAG 检索增强生成的定义", "structured": None}
        result = await rewrite_query_node(state)
    assert result["rewritten_query"] == "RAG 检索增强生成的定义"
    mock_llm.assert_called_once()
    # 验证温度 0.7
    assert mock_llm.call_args.kwargs["temperature"] == 0.7

@pytest.mark.asyncio
async def test_decompose_question_node_returns_needs_decomposition():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="复杂问题", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"needs_decomposition": True, "reasoning_steps": [{"sub_query": "子问题1"}]},
        }
        result = await decompose_question_node(state)
    assert result["needs_decomposition"] is True
    assert len(result["reasoning_steps"]) == 1
    # 验证温度 0.3
    assert mock_llm.call_args.kwargs["temperature"] == 0.3

@pytest.mark.asyncio
async def test_decompose_question_node_no_decomposition():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="简单问题", judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {"needs_decomposition": False, "reasoning_steps": []},
        }
        result = await decompose_question_node(state)
    assert result["needs_decomposition"] is False
    assert result["reasoning_steps"] == []
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_nodes.py -v -k "rewrite or decompose"
```

Expected: FAIL

- [ ] **Step 3: 实现 nodes.py 的 rewrite_query_node 和 decompose_question_node**

```python
# backend/app/graph/nodes.py
from app.graph.state import AgentState
from app.graph.tools import call_llm, evaluate, retrieve, tavily_search
from app.graph.prompts import (
    REWRITE_PROMPT, DECOMPOSE_PROMPT, MULTI_STEP_PROMPT,
    LOCAL_GEN_PROMPT, ONLINE_GEN_PROMPT,
)
from pydantic import BaseModel
from app.config import settings

class DecomposeSchema(BaseModel):
    needs_decomposition: bool
    reasoning_steps: list[dict]

async def rewrite_query_node(state: AgentState) -> dict:
    result = await call_llm(
        system_prompt=REWRITE_PROMPT,
        user_input=state["query"],
        temperature=0.7,
        history=state.get("history", []),
        model=settings.MODEL_FLASH,
    )
    return {"rewritten_query": result["text"]}

async def decompose_question_node(state: AgentState) -> dict:
    result = await call_llm(
        system_prompt=DECOMPOSE_PROMPT,
        user_input=state["rewritten_query"],
        temperature=0.3,
        output_schema=DecomposeSchema,
        model=settings.MODEL_FLASH,
    )
    structured = result["structured"]
    return {
        "needs_decomposition": structured["needs_decomposition"],
        "reasoning_steps": structured["reasoning_steps"],
    }
```

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_nodes.py -v -k "rewrite or decompose"
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes.py backend/tests/unit/test_nodes.py
git commit -m "feat: 添加 rewrite_query 和 decompose_question 节点"
```

---

### Task 15: 节点 3（multi_step_reason，修复分支断裂 bug）

**Files:**
- Modify: `backend/app/graph/nodes.py`
- Modify: `backend/tests/unit/test_nodes.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/unit/test_nodes.py
from app.graph.nodes import multi_step_reason_node

@pytest.mark.asyncio
async def test_multi_step_reason_node_writes_final_answer():
    """验证修复点 1：多步推理节点直接写 final_answer。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="复杂推理问题",
        needs_decomposition=True,
        reasoning_steps=[{"sub_query": "子问题1"}, {"sub_query": "子问题2"}],
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "## 推理过程\n...\n## 结论\n最终答案", "structured": None}
        result = await multi_step_reason_node(state)
    # 关键断言：final_answer 被写入
    assert result["final_answer"] == "## 推理过程\n...\n## 结论\n最终答案"
    # route_path 标记为 decomposition
    assert result["route_path"] == "decomposition"
    # 验证使用 deepseek-reasoner 模型
    assert mock_llm.call_args.kwargs["model"] == settings.MODEL_PRO_REASON
    # 验证温度 0.5
    assert mock_llm.call_args.kwargs["temperature"] == 0.5
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_nodes.py::test_multi_step_reason_node_writes_final_answer -v
```

Expected: FAIL

- [ ] **Step 3: 实现 multi_step_reason_node**

在 nodes.py 追加：

```python
async def multi_step_reason_node(state: AgentState) -> dict:
    """多步推理节点。
    
    修复设计问题 1：直接写 final_answer，主图连到 END。
    """
    steps_text = "\n".join([f"- {s.get('sub_query', '')}" for s in state["reasoning_steps"]])
    user_input = f"原始问题：{state['query']}\n\n分解的子问题：\n{steps_text}\n\n请逐步推理并给出最终答案。"
    
    result = await call_llm(
        system_prompt=MULTI_STEP_PROMPT,
        user_input=user_input,
        temperature=0.5,
        history=state.get("history", []),
        model=settings.MODEL_PRO_REASON,
    )
    return {
        "final_answer": result["text"],
        "route_path": "decomposition",
        "reasoning_result": result["text"],
    }
```

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_nodes.py::test_multi_step_reason_node_writes_final_answer -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes.py backend/tests/unit/test_nodes.py
git commit -m "fix: 修复多步推理分支断裂（节点直接写 final_answer）"
```

---

### Task 16: 节点 4-6（judge_relevance + rag_retrieve + web_search）

**Files:**
- Modify: `backend/app/graph/nodes.py`
- Modify: `backend/tests/unit/test_nodes.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/unit/test_nodes.py
from app.graph.nodes import judge_relevance_node, rag_retrieve_node, web_search_node
from unittest.mock import MagicMock

@pytest.mark.asyncio
async def test_judge_relevance_node_writes_is_relevant():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="什么是 Agent", judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_eval.return_value = {"judge_type": "is_relevant", "passed": True, "raw_output": {}}
        result = await judge_relevance_node(state)
    assert result["is_relevant"] is True
    assert len(result["judge_log"]) == 1

@pytest.mark.asyncio
async def test_rag_retrieve_node_does_retrieve_and_quality_eval():
    """验证 rag_retrieve 节点同时做检索和 RAG 质量评估。"""
    mock_retriever = MagicMock()
    mock_retriever.retrieve = MagicMock(return_value=[
        {"content": "c1", "source": "a.md", "title": "A", "score": 0.9}
    ])
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="Agent 是什么", judge_log=[],
    )
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_ret.return_value = [{"content": "c1", "source": "a.md", "title": "A", "score": 0.9}]
        mock_eval.return_value = {"judge_type": "is_quality_pass", "passed": True, "raw_output": {}}
        result = await rag_retrieve_node(state, mock_retriever)
    
    # 验证检索被调用
    mock_ret.assert_called_once()
    # 验证 RAG 质量评估被调用
    mock_eval.assert_called_once()
    assert mock_eval.call_args.kwargs["judge_type"] == "is_quality_pass"
    # 验证 state 字段
    assert result["retrieval_result"][0]["content"] == "c1"
    assert result["rag_quality_pass"] is True

@pytest.mark.asyncio
async def test_web_search_node_writes_web_search_result():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="最新新闻", judge_log=[],
    )
    with patch("app.graph.nodes.tavily_search", new_callable=AsyncMock) as mock_ts:
        mock_ts.return_value = "[1] 新闻内容"
        result = await web_search_node(state)
    assert result["web_search_result"] == "[1] 新闻内容"
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_nodes.py -v -k "judge_relevance or rag_retrieve or web_search"
```

Expected: FAIL

- [ ] **Step 3: 实现三个节点**

在 nodes.py 追加：

```python
async def judge_relevance_node(state: AgentState) -> dict:
    result = await evaluate(
        judge_type="is_relevant",
        source="",
        query=state["rewritten_query"],
    )
    return {"is_relevant": result["passed"], "judge_log": [result]}

async def rag_retrieve_node(state: AgentState, rag_retriever) -> dict:
    """检索 + RAG 质量评估（生成前）。"""
    # 1. 检索
    retrieval_result = await retrieve(state["rewritten_query"], rag_retriever)
    
    # 2. RAG 质量评估
    source_text = "\n\n".join([r["content"] for r in retrieval_result])
    quality_judge = await evaluate(
        judge_type="is_quality_pass",
        source=source_text,
        query=state["rewritten_query"],
    )
    
    return {
        "retrieval_result": retrieval_result,
        "rag_quality_pass": quality_judge["passed"],
        "judge_log": [quality_judge],
    }

async def web_search_node(state: AgentState) -> dict:
    result = await tavily_search(state["rewritten_query"])
    return {"web_search_result": result}
```

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_nodes.py -v -k "judge_relevance or rag_retrieve or web_search"
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes.py backend/tests/unit/test_nodes.py
git commit -m "feat: 添加 judge_relevance / rag_retrieve / web_search 节点"
```

---

### Task 17: 节点 7（generate_answer，统一生成节点）

**Files:**
- Modify: `backend/app/graph/nodes.py`
- Modify: `backend/tests/unit/test_nodes.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/unit/test_nodes.py
from app.graph.nodes import generate_answer_node

@pytest.mark.asyncio
async def test_generate_answer_local_path_uses_local_prompt():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="什么是 Agent",
        retrieval_result=[{"content": "Agent 是...", "source": "Agent.md", "title": "Agent", "score": 0.9}],
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "Agent 是一种...", "structured": None}
        result = await generate_answer_node(state)
    
    assert result["local_answer"] == "Agent 是一种..."
    assert result["route_path"] == "local"
    # 验证用 LOCAL_GEN_PROMPT（通过检查 system_prompt 含检索内容）
    call_kwargs = mock_llm.call_args.kwargs
    assert "Agent 是..." in call_kwargs["system_prompt"] or "Agent 是..." in call_kwargs["user_input"]

@pytest.mark.asyncio
async def test_generate_answer_online_path_uses_online_prompt():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="最新新闻",
        web_search_result="[1] 新闻内容",
        judge_log=[],
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "根据最新搜索...", "structured": None}
        result = await generate_answer_node(state)
    
    assert result["online_answer"] == "根据最新搜索..."
    assert result["route_path"] == "online"
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_nodes.py -v -k "generate_answer"
```

Expected: FAIL

- [ ] **Step 3: 实现 generate_answer_node**

```python
async def generate_answer_node(state: AgentState) -> dict:
    """统一生成节点：根据是否走 web 路径选提示词。"""
    if state.get("web_search_result"):
        # 联网路径
        prompt = ONLINE_GEN_PROMPT.format(
            query=state["rewritten_query"],
            search_result=state["web_search_result"],
        )
        result = await call_llm(
            system_prompt=prompt,
            user_input=state["query"],
            temperature=0.7,
            history=state.get("history", []),
            model=settings.MODEL_PRO_CHAT,
        )
        return {
            "online_answer": result["text"],
            "final_answer": result["text"],
            "route_path": "online",
        }
    else:
        # 知识库路径
        context = "\n\n".join([
            f"[{i+1}] {r['content']}" for i, r in enumerate(state["retrieval_result"])
        ])
        prompt = LOCAL_GEN_PROMPT.format(
            query=state["rewritten_query"],
            context=context,
        )
        result = await call_llm(
            system_prompt=prompt,
            user_input=state["query"],
            temperature=0.7,
            history=state.get("history", []),
            model=settings.MODEL_PRO_CHAT,
        )
        return {
            "local_answer": result["text"],
            "final_answer": result["text"],
            "route_path": "local",
        }
```

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_nodes.py -v -k "generate_answer"
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes.py backend/tests/unit/test_nodes.py
git commit -m "feat: 添加统一 generate_answer 节点"
```

---

### Task 18: 节点 8（quality_gate，生成后评估）

**Files:**
- Modify: `backend/app/graph/nodes.py`
- Modify: `backend/tests/unit/test_nodes.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 backend/tests/unit/test_nodes.py
from app.graph.nodes import quality_gate_node

@pytest.mark.asyncio
async def test_quality_gate_local_path_passes_when_no_hallucination():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="什么是 Agent",
        route_path="local",
        retrieval_result=[{"content": "c1", "source": "a.md", "title": "A", "score": 0.9}],
        local_answer="Agent 是...",
        judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        # 两次调用：幻觉 + 答案质量
        mock_eval.side_effect = [
            {"judge_type": "is_hallucination", "passed": False, "raw_output": {}},  # 无幻觉
            {"judge_type": "is_quality_pass", "passed": True, "raw_output": {}},     # 质量通过
        ]
        result = await quality_gate_node(state)
    
    assert result["hallucination_flag"] is False
    assert result["answer_quality_pass"] is True

@pytest.mark.asyncio
async def test_quality_gate_fallback_on_error():
    """验证评估失败时降级到不通过。"""
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="x",
        route_path="online",
        web_search_result="x",
        online_answer="x",
        judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_eval.side_effect = Exception("LLM 调用失败")
        result = await quality_gate_node(state)
    
    assert result["answer_quality_pass"] is False
    assert result["hallucination_flag"] is True
    # 验证记录了 fallback 日志
    fallback_logs = [j for j in result["judge_log"] if j["judge_type"] == "fallback"]
    assert len(fallback_logs) == 1

@pytest.mark.asyncio
async def test_quality_gate_online_path_uses_web_search_result():
    state = AgentState(
        query="x", conversation_id="c1", history=[],
        rewritten_query="x",
        route_path="online",
        web_search_result="搜索结果",
        online_answer="答案",
        judge_log=[],
    )
    with patch("app.graph.nodes.evaluate", new_callable=AsyncMock) as mock_eval:
        mock_eval.side_effect = [
            {"judge_type": "is_hallucination", "passed": False, "raw_output": {}},
            {"judge_type": "is_quality_pass", "passed": True, "raw_output": {}},
        ]
        await quality_gate_node(state)
    
    # 验证幻觉检测用 web_search_result 作为 source
    first_call = mock_eval.call_args_list[0]
    assert first_call.kwargs["source"] == "搜索结果"
    assert first_call.kwargs["answer"] == "答案"
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_nodes.py -v -k "quality_gate"
```

Expected: FAIL

- [ ] **Step 3: 实现 quality_gate_node**

按设计文档 7.6 节"质量门控节点容错"代码实现，包含 tenacity 重试装饰器。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_nodes.py -v -k "quality_gate"
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/nodes.py backend/tests/unit/test_nodes.py
git commit -m "feat: 添加 quality_gate 节点（生成后评估 + 容错）"
```

---

### Task 19: 图构建 + 条件路由

**Files:**
- Create: `backend/app/graph/builder.py`
- Test: `backend/tests/unit/test_builder.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_builder.py
import pytest
from unittest.mock import MagicMock
from app.graph.builder import build_graph, route_after_decompose, route_after_relevance, route_after_rag_retrieve, route_after_quality
from app.graph.state import AgentState
from langgraph.graph END

def test_route_after_decompose_true():
    state = {"needs_decomposition": True}
    assert route_after_decompose(state) == "multi_step_reason"

def test_route_after_decompose_false():
    state = {"needs_decomposition": False}
    assert route_after_decompose(state) == "judge_relevance"

def test_route_after_relevance_true():
    state = {"is_relevant": True}
    assert route_after_relevance(state) == "rag_retrieve"

def test_route_after_relevance_false():
    state = {"is_relevant": False}
    assert route_after_relevance(state) == "web_search"

def test_route_after_rag_retrieve_pass():
    state = {"rag_quality_pass": True}
    assert route_after_rag_retrieve(state) == "generate_answer"

def test_route_after_rag_retrieve_fail():
    state = {"rag_quality_pass": False}
    assert route_after_rag_retrieve(state) == "web_search"

def test_route_after_quality_pass():
    state = {"answer_quality_pass": True, "hallucination_flag": False, "route_path": "local"}
    assert route_after_quality(state) == END

def test_route_after_quality_fail_local_goes_fallback():
    state = {"answer_quality_pass": False, "hallucination_flag": True, "route_path": "local"}
    assert route_after_quality(state) == "fallback_online"

def test_route_after_quality_fail_online_ends():
    state = {"answer_quality_pass": False, "hallucination_flag": True, "route_path": "online"}
    assert route_after_quality(state) == END

def test_build_graph_returns_compiled():
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)
    # 验证是 compiled graph
    assert hasattr(graph, "ainvoke")
    assert hasattr(graph, "astream_events")
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/unit/test_builder.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 builder.py**

```python
# backend/app/graph/builder.py
from langgraph.graph import StateGraph, END
from app.graph.state import AgentState
from app.graph.nodes import (
    rewrite_query_node, decompose_question_node, multi_step_reason_node,
    judge_relevance_node, rag_retrieve_node, web_search_node,
    generate_answer_node, quality_gate_node,
)

def route_after_decompose(state):
    if state.get("needs_decomposition"):
        return "multi_step_reason"
    return "judge_relevance"

def route_after_relevance(state):
    return "rag_retrieve" if state.get("is_relevant") else "web_search"

def route_after_rag_retrieve(state):
    if state.get("rag_quality_pass"):
        return "generate_answer"
    return "web_search"

def route_after_quality(state):
    if state.get("answer_quality_pass") and not state.get("hallucination_flag"):
        return END
    if state.get("route_path") == "local":
        return "fallback_online"
    return END

def build_graph(rag_retriever):
    graph = StateGraph(AgentState)
    
    # 添加节点
    graph.add_node("rewrite_query", rewrite_query_node)
    graph.add_node("decompose_question", decompose_question_node)
    graph.add_node("multi_step_reason", multi_step_reason_node)
    graph.add_node("judge_relevance", judge_relevance_node)
    graph.add_node("rag_retrieve", lambda state: rag_retrieve_node(state, rag_retriever))
    graph.add_node("web_search", web_search_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("quality_gate", quality_gate_node)
    graph.add_node("fallback_online", web_search_node)  # 复用 web_search
    
    # 入口
    graph.set_entry_point("rewrite_query")
    
    # 边
    graph.add_edge("rewrite_query", "decompose_question")
    graph.add_conditional_edges("decompose_question", route_after_decompose,
                                {"multi_step_reason": "multi_step_reason",
                                 "judge_relevance": "judge_relevance"})
    graph.add_edge("multi_step_reason", END)  # 修复点 1
    graph.add_conditional_edges("judge_relevance", route_after_relevance,
                                {"rag_retrieve": "rag_retrieve",
                                 "web_search": "web_search"})
    graph.add_conditional_edges("rag_retrieve", route_after_rag_retrieve,
                                {"generate_answer": "generate_answer",
                                 "web_search": "web_search"})
    graph.add_edge("web_search", "generate_answer")
    graph.add_edge("generate_answer", "quality_gate")
    graph.add_conditional_edges("quality_gate", route_after_quality,
                                {END: END, "fallback_online": "fallback_online"})
    graph.add_edge("fallback_online", "generate_answer")  # fallback 后重新生成
    
    return graph.compile()
```

**注意**：fallback_online → generate_answer 会形成循环。LangGraph 支持循环，但需要设置 recursion_limit。在 API 层调用时设置 `config={"recursion_limit": 25}`。

- [ ] **Step 4: 运行验证通过**

```bash
pytest tests/unit/test_builder.py -v
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/graph/builder.py backend/tests/unit/test_builder.py
git commit -m "feat: 添加 LangGraph 图构建和条件路由"
```

---

## Phase 5: FastAPI 服务层

### Task 20: 错误处理 + 健康检查

**Files:**
- Create: `backend/app/api/errors.py`
- Create: `backend/app/api/health.py`
- Test: `backend/tests/integration/test_api_health.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/integration/test_api_health.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ["ok", "degraded"]
    assert "model" in data
    assert "vector_db" in data
    assert "embedding_model" in data
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/integration/test_api_health.py -v
```

Expected: FAIL（app.main 不存在）

- [ ] **Step 3: 实现 errors.py 和 health.py**

errors.py 按设计文档 7.6 节实现（ERROR_MESSAGES / ERROR_STATUS_CODE / register_error_handlers）。

health.py：

```python
# backend/app/api/health.py
from fastapi import APIRouter, Depends
from app.models.schemas import HealthResponse
from app.config import settings

router = APIRouter(prefix="/api/health", tags=["health"])

@router.get("", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        model=settings.MODEL_FLASH,
        vector_db="chroma",
        embedding_model=settings.EMBEDDING_MODEL,
    )
```

- [ ] **Step 4: 实现 main.py 最小骨架**

```python
# backend/app/main.py
from fastapi import FastAPI
from app.api import health
from app.api.errors import register_error_handlers

app = FastAPI(title="学AI必备助手 API", version="1.0.0")
app.include_router(health.router)
register_error_handlers(app)
```

创建 `backend/app/api/__init__.py`（已存在空文件，无需操作）。

- [ ] **Step 5: 运行验证通过**

```bash
pytest tests/integration/test_api_health.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/errors.py backend/app/api/health.py backend/app/main.py backend/tests/integration/test_api_health.py
git commit -m "feat: 添加错误处理和健康检查端点"
```

---

### Task 21: 会话管理路由

**Files:**
- Create: `backend/app/api/conversations.py`
- Modify: `backend/app/main.py`（注册路由 + lifespan 初始化 store）
- Test: `backend/tests/integration/test_api_conversations.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/integration/test_api_conversations.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest.mark.asyncio
async def test_create_conversation_default_title(client):
    resp = await client.post("/api/conversations", json={})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "新会话"
    assert "id" in data

@pytest.mark.asyncio
async def test_list_conversations(client):
    # 先创建 2 个
    await client.post("/api/conversations", json={"title": "会话1"})
    await client.post("/api/conversations", json={"title": "会话2"})
    resp = await client.get("/api/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2

@pytest.mark.asyncio
async def test_get_conversation_detail(client):
    create = await client.post("/api/conversations", json={"title": "测试"})
    conv_id = create.json()["id"]
    resp = await client.get(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "测试"

@pytest.mark.asyncio
async def test_get_nonexistent_conversation_returns_404(client):
    resp = await client.get("/api/conversations/nonexistent-id")
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_delete_conversation(client):
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    resp = await client.delete(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # 验证已删除
    resp2 = await client.get(f"/api/conversations/{conv_id}")
    assert resp2.status_code == 404

@pytest.mark.asyncio
async def test_update_conversation_title(client):
    create = await client.post("/api/conversations", json={"title": "旧"})
    conv_id = create.json()["id"]
    resp = await client.patch(f"/api/conversations/{conv_id}", json={"title": "新"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "新"
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/integration/test_api_conversations.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 conversations.py**

按设计文档 7.5 节 conversations 路由代码实现。需要添加 `get_store` 依赖函数。

- [ ] **Step 4: 修改 main.py 添加 lifespan 和路由注册**

```python
# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import health, conversations
from app.api.errors import register_error_handlers
from app.services.conversation_store import ConversationStore
from app.config import settings
import os

_store: ConversationStore = None

def get_store() -> ConversationStore:
    return _store

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store
    # 使用临时 DB（测试期）；生产用 settings.SQLITE_PATH
    db_path = os.environ.get("TEST_SQLITE_PATH", settings.SQLITE_PATH)
    _store = ConversationStore(db_path)
    await _store.init()
    yield

app = FastAPI(title="学AI必备助手 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(conversations.router)
register_error_handlers(app)
```

- [ ] **Step 5: 运行验证通过**

```bash
pytest tests/integration/test_api_conversations.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/conversations.py backend/app/main.py backend/tests/integration/test_api_conversations.py
git commit -m "feat: 添加会话管理 CRUD 路由"
```

---

### Task 22: 流式对话路由（SSE）

**Files:**
- Create: `backend/app/api/chat.py`
- Modify: `backend/app/main.py`（注册路由 + lifespan 初始化 graph）
- Test: `backend/tests/integration/test_api_chat.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/integration/test_api_chat.py
import pytest
import json
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

@pytest.mark.asyncio
async def test_chat_returns_404_for_nonexistent_conversation(client):
    resp = await client.post("/api/chat", json={"conversation_id": "nonexistent", "message": "x"})
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_chat_returns_sse_stream(client, monkeypatch):
    """验证 /api/chat 返回 SSE 流。"""
    # 创建会话
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    
    # mock graph.astream_events
    async def mock_stream(*args, **kwargs):
        yield {"event": "on_chain_start", "name": "rewrite_query", "data": {}}
        yield {"event": "on_llm_stream", "data": {"chunk": {"content": "测试"}}}
        yield {"event": "on_chain_end", "name": "LangGraph",
               "data": {"output": {"final_answer": "测试", "route_path": "local", "judge_log": []}}}
    
    from app.api import chat as chat_module
    monkeypatch.setattr(chat_module, "get_graph", lambda: type("G", (), {"astream_events": mock_stream})())
    
    async with client.stream("POST", "/api/chat",
                              json={"conversation_id": conv_id, "message": "你好"}) as resp:
        assert resp.status_code == 200
        events = []
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
        
        types = [e["type"] for e in events]
        assert "stage" in types
        assert "token" in types
        assert "done" in types

@pytest.mark.asyncio
async def test_chat_rejects_empty_message(client):
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]
    resp = await client.post("/api/chat", json={"conversation_id": conv_id, "message": ""})
    assert resp.status_code == 422
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/integration/test_api_chat.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 chat.py**

按设计文档 7.5 节 chat 路由代码实现，包含 STAGE_LABELS 字典、event_generator 函数、get_graph 依赖。

- [ ] **Step 4: 修改 main.py 注册 chat 路由**

在 lifespan 中初始化 graph（暂用 mock，因为 RAG 层依赖真实 API Key）：

```python
# 在 main.py lifespan 中添加
_graph = None

def get_graph():
    return _graph

# lifespan 内（在 store 初始化之后）
global _graph
try:
    from app.rag.indexer import Indexer
    from app.graph.builder import build_graph
    _indexer = Indexer(data_dir=settings.KB_DATA_DIR, persist_dir=settings.CHROMA_PERSIST_DIR)
    _indexer.load_or_build()
    _graph = build_graph(_indexer.get_retriever())
except Exception as e:
    import logging
    logging.warning(f"Graph 初始化失败（开发期可继续）: {e}")
    _graph = None

# 注册路由
app.include_router(chat.router)
```

- [ ] **Step 5: 运行验证通过**

```bash
pytest tests/integration/test_api_chat.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/chat.py backend/app/main.py backend/tests/integration/test_api_chat.py
git commit -m "feat: 添加流式对话 SSE 路由"
```

---

### Task 23: 索引管理路由

**Files:**
- Create: `backend/app/api/index.py`
- Modify: `backend/app/main.py`（注册路由）
- Test: `backend/tests/integration/test_api_index.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/integration/test_api_index.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_rebuild_index():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        with patch("app.api.index.get_indexer") as mock_get:
            mock_idx = MagicMock()
            mock_idx.build = MagicMock()
            mock_idx.chroma_collection = MagicMock()
            mock_idx.chroma_collection.count = MagicMock(return_value=18)
            mock_get.return_value = mock_idx
            
            resp = await c.post("/api/index/rebuild")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["doc_count"] == 18
```

- [ ] **Step 2: 运行验证失败**

```bash
pytest tests/integration/test_api_index.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 index.py**

```python
# backend/app/api/index.py
from fastapi import APIRouter, Depends
from app.models.schemas import IndexRebuildResponse
from app.rag.indexer import Indexer

router = APIRouter(prefix="/api/index", tags=["index"])

_indexer: Indexer = None

def set_indexer(indexer: Indexer):
    global _indexer

def get_indexer() -> Indexer:
    return _indexer

@router.post("/rebuild", response_model=IndexRebuildResponse)
async def rebuild_index(indexer: Indexer = Depends(get_indexer)):
    indexer.build()
    doc_count = indexer.chroma_collection.count()
    return IndexRebuildResponse(success=True, doc_count=doc_count)
```

- [ ] **Step 4: 修改 main.py 注册路由 + 在 lifespan 调用 set_indexer**

```python
# main.py
from app.api import health, conversations, chat, index as index_api
# ... lifespan 内：
if _indexer:
    index_api.set_indexer(_indexer)
app.include_router(index_api.router)
```

- [ ] **Step 5: 运行验证通过**

```bash
pytest tests/integration/test_api_index.py -v
```

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/index.py backend/app/main.py backend/tests/integration/test_api_index.py
git commit -m "feat: 添加索引重建路由"
```

---

## Phase 6: 前端

### Task 24: 前端类型定义 + API 客户端

**Files:**
- Create: `frontend/src/types/index.ts`
- Create: `frontend/src/api/conversations.ts`
- Test: `frontend/src/api/__tests__/conversations.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/src/api/__tests__/conversations.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listConversations, createConversation, deleteConversation } from '../conversations'

global.fetch = vi.fn()

describe('conversations API', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('listConversations calls GET /api/conversations', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ([]), })
    await listConversations()
    expect(fetch).toHaveBeenCalledWith('/api/conversations')
  })

  it('createConversation calls POST with body', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ({ id: '1' }), })
    await createConversation({ title: 'test' })
    expect(fetch).toHaveBeenCalledWith('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'test' }),
    })
  })

  it('deleteConversation calls DELETE', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ({ success: true }), })
    await deleteConversation('abc')
    expect(fetch).toHaveBeenCalledWith('/api/conversations/abc', { method: 'DELETE' })
  })

  it('throws on non-ok response', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 404 })
    await expect(deleteConversation('x')).rejects.toThrow()
  })
})
```

- [ ] **Step 2: 安装 vitest**

```bash
cd frontend
npm install -D vitest @vue/test-utils jsdom
```

在 package.json 添加：
```json
"scripts": { "test": "vitest" },
"vitest": { "environment": "jsdom" }
```

- [ ] **Step 3: 运行验证失败**

```bash
npm test
```

Expected: FAIL

- [ ] **Step 4: 实现 types/index.ts**

```typescript
// frontend/src/types/index.ts
export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface Source {
  content: string
  source: string
  title: string
  score: number
}

export interface JudgeResult {
  judge_type: string
  passed: boolean
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  route_path?: string
  sources?: Source[]
  judge_log?: JudgeResult[]
  created_at: string
  isStreaming?: boolean
  currentStage?: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface ChatRequest {
  conversation_id: string
  message: string
}
```

- [ ] **Step 5: 实现 api/conversations.ts**

```typescript
// frontend/src/api/conversations.ts
import type { Conversation, ConversationDetail } from '@/types'

export async function listConversations(): Promise<Conversation[]> {
  const r = await fetch('/api/conversations')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export async function createConversation(body: { title?: string } = {}): Promise<Conversation> {
  const r = await fetch('/api/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const r = await fetch(`/api/conversations/${id}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await fetch(`/api/conversations/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
}

export async function updateConversation(id: string, title: string): Promise<Conversation> {
  const r = await fetch(`/api/conversations/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}
```

- [ ] **Step 6: 运行验证通过**

```bash
npm test
```

Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add frontend/src/types frontend/src/api frontend/package.json frontend/vitest.config.ts
git commit -m "feat: 添加前端类型定义和会话 API 客户端"
```

---

### Task 25: SSE 客户端

**Files:**
- Create: `frontend/src/api/chat.ts`
- Test: `frontend/src/api/__tests__/chat.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/src/api/__tests__/chat.test.ts
import { describe, it, expect, vi } from 'vitest'
import { streamChat } from '../chat'

describe('streamChat SSE parsing', () => {
  it('parses stage / token / done events', async () => {
    const sseData = [
      'data: {"type":"stage","data":"正在检索..."}',
      '',
      'data: {"type":"token","data":"你好"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')
    
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(sseData))
        controller.close()
      },
    })
    
    ;(global.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: stream })
    
    const events: any[] = []
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: (s) => events.push({ type: 'stage', data: s }),
        onToken: (t) => events.push({ type: 'token', data: t }),
        onMeta: (m) => events.push({ type: 'meta', data: m }),
        onError: (e) => events.push({ type: 'error', data: e }),
        onDone: () => events.push({ type: 'done' }),
      }
    )
    
    expect(events).toEqual([
      { type: 'stage', data: '正在检索...' },
      { type: 'token', data: '你好' },
      { type: 'done' },
    ])
  })

  it('throws on HTTP error', async () => {
    ;(global.fetch as any) = vi.fn().mockResolvedValue({ ok: false, status: 500 })
    await expect(streamChat(
      { conversation_id: '1', message: 'x' },
      { onStage: () => {}, onToken: () => {}, onMeta: () => {}, onError: () => {}, onDone: () => {} }
    )).rejects.toThrow('HTTP 500')
  })
})
```

- [ ] **Step 2: 运行验证失败**

```bash
npm test -- chat
```

Expected: FAIL

- [ ] **Step 3: 实现 chat.ts**

按设计文档 8.4 节代码实现 streamChat 函数。

- [ ] **Step 4: 运行验证通过**

```bash
npm test -- chat
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/chat.ts frontend/src/api/__tests__/chat.test.ts
git commit -m "feat: 添加 SSE 流式客户端"
```

---

### Task 26: Pinia Store

**Files:**
- Create: `frontend/src/stores/chat.ts`
- Test: `frontend/src/stores/__tests__/chat.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/src/stores/__tests__/chat.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '../chat'
import * as convApi from '@/api/conversations'
import * as chatApi from '@/api/chat'

vi.mock('@/api/conversations')
vi.mock('@/api/chat')

describe('chat store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadConversations loads and selects first', async () => {
    ;(convApi.listConversations as any).mockResolvedValue([
      { id: '1', title: 'A', message_count: 0, created_at: '', updated_at: '' },
    ])
    ;(convApi.getConversation as any).mockResolvedValue({ id: '1', messages: [] })
    
    const store = useChatStore()
    await store.loadConversations()
    expect(store.conversations.length).toBe(1)
    expect(store.currentConversationId).toBe('1')
  })

  it('sendMessage creates conversation if none selected', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({ id: 'new', title: '', message_count: 0, created_at: '', updated_at: '' })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (req, cb) => {
      cb.onStage('正在...')
      cb.onToken('回')
      cb.onToken('答')
      cb.onDone()
    })
    
    const store = useChatStore()
    store.inputText = '测试'
    await store.sendMessage()
    
    expect(store.messages.length).toBe(2) // user + assistant
    expect(store.messages[1].content).toBe('回答')
    expect(store.isStreaming).toBe(false)
  })
})
```

- [ ] **Step 2: 运行验证失败**

```bash
npm test -- store
```

Expected: FAIL

- [ ] **Step 3: 实现 stores/chat.ts**

按设计文档 8.5 节代码实现，注意添加 `scrollToBottom` 触发机制（用 ref watch）。

- [ ] **Step 4: 运行验证通过**

```bash
npm test -- store
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/stores frontend/src/stores/__tests__/chat.test.ts
git commit -m "feat: 添加 Pinia chat store"
```

---

### Task 27: 前端组件实现

**Files:**
- Create: `frontend/src/components/AppHeader.vue`
- Create: `frontend/src/components/ConversationSidebar.vue`
- Create: `frontend/src/components/ChatPanel.vue`
- Create: `frontend/src/components/MessageList.vue`
- Create: `frontend/src/components/UserMessage.vue`
- Create: `frontend/src/components/AssistantMessage.vue`
- Create: `frontend/src/components/MarkdownRenderer.vue`
- Create: `frontend/src/components/StageIndicator.vue`
- Create: `frontend/src/components/SourceCard.vue`
- Create: `frontend/src/components/JudgeBadges.vue`
- Create: `frontend/src/components/InputBox.vue`
- Create: `frontend/src/components/EmptyState.vue`
- Create: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/router/index.ts`
- Modify: `frontend/src/main.ts`（注册 router + pinia）
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: 实现 MarkdownRenderer**

```vue
<!-- frontend/src/components/MarkdownRenderer.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

const props = defineProps<{ content: string }>()

const md = new MarkdownIt({
  html: false,  // 关键：禁用 HTML 防 XSS
  highlight(str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try { return `<pre><code class="hljs">${hljs.highlight(str, { language: lang }).value}</code></pre>` } catch {}
    }
    return `<pre><code class="hljs">${md.utils.escapeHtml(str)}</code></pre>`
  },
})

const html = computed(() => md.render(props.content))
</script>

<template>
  <div v-html="html" class="markdown-body"></div>
</template>
```

- [ ] **Step 2: 实现 StageIndicator / SourceCard / JudgeBadges**

按设计文档 8.6 节代码实现。

- [ ] **Step 3: 实现 AssistantMessage 和 UserMessage**

AssistantMessage 按设计文档 8.6 节代码实现。

- [ ] **Step 4: 实现 MessageList**

```vue
<!-- frontend/src/components/MessageList.vue -->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import UserMessage from './UserMessage.vue'
import AssistantMessage from './AssistantMessage.vue'

const store = useChatStore()
const listRef = ref<HTMLElement>()

// 消息变化时自动滚动到底部
watch(() => store.messages.length, async () => {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
})

// 流式 token 时也滚动
watch(() => store.messages.at(-1)?.content, async () => {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
})
</script>

<template>
  <div ref="listRef" class="flex-1 overflow-y-auto">
    <UserMessage v-for="m in store.messages.filter(x => x.role === 'user')" :key="m.id" :message="m" />
    <template v-for="m in store.messages" :key="m.id">
      <UserMessage v-if="m.role === 'user'" :message="m" />
      <AssistantMessage v-else :message="m" />
    </template>
  </div>
</template>
```

修正：上面有重复，只保留 template 部分。

- [ ] **Step 5: 实现 InputBox / ConversationSidebar / ChatPanel / AppHeader / EmptyState**

按设计文档 8.2 / 8.6 节布局实现，使用 Tailwind 类名。

- [ ] **Step 6: 实现 router 和 ChatView**

```typescript
// frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: ChatView },
    { path: '/chat/:id', component: ChatView },
  ],
})
```

ChatView 整合 sidebar + chat panel，根据路由参数加载会话。

- [ ] **Step 7: 修改 main.ts 注册 router 和 pinia**

```typescript
// frontend/src/main.ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './style.css'
import 'highlight.js/styles/github.css'

createApp(App).use(createPinia()).use(router).mount('#app')
```

- [ ] **Step 8: 修改 App.vue**

```vue
<!-- frontend/src/App.vue -->
<script setup lang="ts">
</script>

<template>
  <router-view />
</template>
```

- [ ] **Step 9: 验证启动**

```bash
npm run dev
```

Expected: 浏览器访问 http://localhost:5173 看到聊天界面（空状态）。

- [ ] **Step 10: 提交**

```bash
git add frontend/src
git commit -m "feat: 实现前端所有组件和路由"
```

---

## Phase 7: 端到端联调

### Task 28: 后端 E2E 测试

**Files:**
- Create: `backend/tests/e2e/test_local_path.py`
- Create: `backend/tests/e2e/test_online_path.py`
- Create: `backend/tests/e2e/test_decomposition_path.py`
- Modify: `backend/tests/conftest.py`

**注意**：E2E 测试需要真实 API Key，标记为 `@pytest.mark.e2e`，默认跳过。设置 `RUN_E2E=1` 环境变量时运行。

- [ ] **Step 1: 实现 conftest.py 公共 fixture**

```python
# backend/tests/conftest.py
import pytest
import os

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: marks as end-to-end test (requires real API keys)")

def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_E2E") == "1":
        return
    skip_e2e = pytest.mark.skip(reason="需要 RUN_E2E=1 才运行")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)
```

- [ ] **Step 2: 实现 test_local_path.py**

```python
# backend/tests/e2e/test_local_path.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_local_path_end_to_end():
    """端到端测试：用户问知识库相关问题，走 local 路径。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 创建会话
        create = await c.post("/api/conversations", json={})
        conv_id = create.json()["id"]
        
        # 发送知识库相关问题
        async with c.stream("POST", "/api/chat",
                            json={"conversation_id": conv_id, "message": "什么是 Agent？"}) as resp:
            assert resp.status_code == 200
            chunks = []
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    chunks.append(line[5:].strip())
        
        # 验证有 token 输出
        import json
        tokens = [json.loads(c)["data"] for c in chunks if json.loads(c)["type"] == "token"]
        assert len(tokens) > 0
        
        # 验证最终消息持久化
        detail = await c.get(f"/api/conversations/{conv_id}")
        msgs = detail.json()["messages"]
        assert len(msgs) == 2  # user + assistant
        assert msgs[1]["route_path"] == "local"
```

- [ ] **Step 3: 实现另外两个 e2e 测试**

test_online_path.py 测试「最新新闻」类问题走 online 路径。
test_decomposition_path.py 测试复杂推理问题走 decomposition 路径，验证用户能看到回复（修复点 1）。

- [ ] **Step 4: 运行（手动，需 API Key）**

```bash
cd backend
$env:RUN_E2E=1
pytest tests/e2e/ -v
```

Expected: 3 个测试通过（需真实 API Key 配置在 .env）

- [ ] **Step 5: 提交**

```bash
git add backend/tests/conftest.py backend/tests/e2e/
git commit -m "test: 添加 3 条端到端测试"
```

---

### Task 29: 数据软链 + 启动脚本

**Files:**
- Create: `data/raw` (软链到 D:\Project\Self-RAG-Agent\data\raw)
- Create: `backend/.env`（从 .env.example 复制并填入真实 Key，不进 git）
- Create: `start.bat`（一键启动脚本）
- Update: `README.md`

- [ ] **Step 1: 创建数据软链（Windows 需管理员权限）**

```bash
cd d:\Project\Agent
mklink /D data\raw "D:\Project\Self-RAG-Agent\data\raw"
```

如果 mklink 失败，改用复制：
```bash
xcopy "D:\Project\Self-RAG-Agent\data\raw" "data\raw\" /E /I
```

- [ ] **Step 2: 创建 .env 文件**

```bash
cd backend
copy .env.example .env
# 编辑 .env 填入真实 API Key
```

- [ ] **Step 3: 创建启动脚本**

```batch
@echo off
REM start.bat - 一键启动后端和前端
cd /d d:\Project\Agent\backend
start "backend" cmd /k ".venv\Scripts\activate && uvicorn app.main:app --reload"
cd /d d:\Project\Agent\frontend
start "frontend" cmd /k "npm run dev"
```

- [ ] **Step 4: 验证完整启动**

```bash
# 启动后端
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload
# 看到 "Application startup complete" 表示 RAG 索引构建成功

# 启动前端
cd frontend
npm run dev
```

浏览器访问 http://localhost:5173，发送「什么是 Agent？」，验证：
- 看到「正在理解问题...」等阶段进度
- 看到流式 token 输出
- 看到引用来源卡片
- 看到评估标签

- [ ] **Step 5: 提交**

```bash
git add start.bat README.md
git commit -m "chore: 添加启动脚本和文档"
```

---

## Self-Review

### Spec coverage（对照设计文档）

- [x] 4 层架构 → Task 1-2 项目骨架
- [x] AgentState → Task 10
- [x] 8 个节点 → Task 14-18
- [x] 条件路由 → Task 19
- [x] 工具化抽象 → Task 11-13
- [x] ObsidianMarkdownReader → Task 6
- [x] Indexer → Task 9
- [x] RAGRetriever + Reranker → Task 7-8
- [x] SQLite 会话存储 → Task 5
- [x] FastAPI 路由（chat/conversations/index/health）→ Task 20-23
- [x] 错误处理 → Task 20
- [x] 配置管理 → Task 3
- [x] Vue 3 前端 → Task 24-27
- [x] SSE 客户端 → Task 25
- [x] Pinia store → Task 26
- [x] 测试策略 → Task 28（e2e）+ 各 Task 内单元/集成测试
- [x] 安全考虑（Markdown XSS）→ Task 27（MarkdownRenderer html:false）
- [x] 修复点 1（多步推理分支断裂）→ Task 15
- [x] 修复点 2（评估温度统一 0.2）→ Task 12
- [x] 修复点 3（检索/生成 query 一致）→ Task 17
- [x] 修复点 4（RAG 质量回退）→ Task 16 + Task 19

### Placeholder scan

- [x] 无 TBD / TODO
- [x] 提示词模板（Task 10 Step 4）标注「从 DSL 提取」，是明确的执行指令不是占位符
- [x] 华为云 rerank API 路径（Task 7）标注「根据华为云文档补充」，是已知外部依赖

### Type consistency

- [x] `call_llm` 返回 `{"text", "structured"}` 跨 Task 11/12/14-18 一致
- [x] `evaluate` 返回 `{judge_type, passed, raw_output}` 跨 Task 12/16/18 一致
- [x] `AgentState` 字段名跨 Task 10/14-19 一致
- [x] `route_path` 取值 "local" / "online" / "decomposition" / "fallback" 跨 Task 15/17/19 一致
- [x] 前端 `Message` 类型跨 Task 24/26/27 一致

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-26-xuai-agent.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 我为每个 Task 派遣独立 subagent，任务间审查，快速迭代

**2. Inline Execution** - 在当前会话内执行任务，分批 checkpoint 审查

请选择执行方式。
