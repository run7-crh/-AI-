# 学AI必备助手 - 设计规格文档

**文档日期**：2026-07-26
**项目路径**：`d:\Project\Agent\`
**源工作流**：Dify advanced-chat 应用「学AI必备助手」（DSL 文件：`学AI必备助手.yml`）
**目标技术栈**：LlamaIndex（RAG）+ LangGraph（编排）+ FastAPI（服务）+ Vue 3（前端）

---

## 1. 项目背景与目标

### 1.1 背景

用户在 Dify 上搭建了一个名为「学AI必备助手」的 advanced-chat 知识库问答 Agent，针对想入门大模型和 Agent 开发的萌新用户，基于 18 篇 Obsidian Markdown 笔记（位于 `D:\Project\Self-RAG-Agent\data\raw`）提供概念问答服务。

原始 Dify 工作流包含 24 个节点，采用 **双路径架构 + 三重质量门控** 设计：

- **双路径**：根据问题相关性判断，走「知识库检索」或「Tavily 联网搜索」
- **三重质量门控**：RAG 质量评估 → 幻觉检测 → 答案质量评估
- **多步推理分支**：复杂问题分解为子问题逐步推理

### 1.2 目标

脱离 Dify 平台，使用代码框架重新实现该工作流，**修复已识别的设计问题，保留原始架构**，使其成为可独立部署、可长期维护的产品级应用。

### 1.3 非目标（YAGNI）

- 不做用户系统/权限隔离（开发期单用户）
- 不做多知识库管理（只有一个固定知识库）
- 不做前端调试面板（API 留接口，前端后补）
- 不做会话标题自动生成
- 不做生产级监控/告警

---

## 2. 原始工作流分析与问题识别

### 2.1 原始工作流结构

```
用户输入
  → 意图改写（Query Rewrite, deepseek-v4-flash, temp=0.7）
  → 问题分解判断（是否需要多步推理）
      ├─ true  → 多步推理执行（deepseek-v4-pro, temp=0.5）
      └─ false → 问题相关性判断（知识库 vs 联网）
                  ├─ 相关   → 知识检索 → RAG质量评估
                  │             ├─ 通过 → LLM本地生成 → 幻觉检测 → 答案质量评估 → 知识库回复
                  │             └─ 不通过 → 兜底转联网 ↓
                  └─ 不相关 → Tavily Search → LLM联网生成 → 幻觉检测 → 答案质量评估 → 联网回复
```

### 2.2 识别出的 5 个设计问题

| # | 严重度 | 问题 | 修复策略 |
|---|--------|------|----------|
| 1 | 🔴 严重 bug | 多步推理分支断裂：节点 `1785059818901` 输出未连到任何 answer 节点，用户看不到回复 | `multi_step_reason` 节点直接写 `final_answer`，主图连到 END |
| 2 | 🟡 优化 | 评估节点温度不一致：幻觉检测-本地 `temp=0.1`，但幻觉检测-联网、答案质量评估-联网 `temp=0.7` | `evaluate()` 工具统一硬编码 `temp=0.2` |
| 3 | 🟡 优化 | 检索/生成 query 不一致：检索用改写后 query，生成用原始 query | `generate_answer` 节点用 `rewritten_query` |
| 4 | 🟡 优化 | RAG 质量差直接转联网，逻辑可疑 | `fallback_online` 子路径兜底 |
| 5 | 🟢 整洁 | 重复 answer 节点 | 合并为 `generate_answer` 单节点 |

### 2.3 修复范围确认

**采用「修复 bug 保留架构」策略**：执行问题 1-4 的修复，问题 5 作为方案 C 工具化抽象的自然结果，不单独处理。不重构 RAG 质量回退策略等深层逻辑。

---

## 3. 技术栈选型

| 层 | 技术 | 版本 | 用途 |
|----|------|------|------|
| RAG 检索层 | LlamaIndex | 0.10+ | 文档读取、向量化、检索 |
| Agent 编排层 | LangGraph | 0.2+ | 状态机、节点编排 |
| 服务层 | FastAPI | 0.110+ | REST API、SSE 流式 |
| 前端 | Vue 3 + TypeScript | 3.4+ | SPA 聊天界面 |
| 向量数据库 | Chroma | 0.5+ | 本地持久化 |
| LLM | DeepSeek 官方 API | - | `deepseek-chat` / `deepseek-reasoner` |
| Embedding | 华为云 MaaS | - | `bge-large-zh-v1.5` |
| Reranker | 华为云 MaaS | - | `bge-reranker-v2-m3`（与 DSL 一致） |
| 联网搜索 | Tavily API | - | basic 模式，max_results=5 |
| 会话存储 | SQLite + aiosqlite | - | 文件型数据库，零配置 |
| 前端状态 | Pinia | 2+ | Vue 3 官方推荐 |
| 前端样式 | Tailwind CSS | 3+ | 原子 CSS，无组件库 |
| Markdown 渲染 | markdown-it + highlight.js | - | Markdown + 代码高亮 |

### 3.1 模型映射

DeepSeek 官方 API 仅提供两个模型，对 DSL 模型名映射如下：

| DSL 模型名 | 映射到 | 用途 |
|-----------|--------|------|
| `deepseek-v4-flash` | `deepseek-chat` | 评估/判断/改写类节点（低成本、快） |
| `deepseek-v4-pro`（联网生成） | `deepseek-chat` | 联网答案生成 |
| `deepseek-v4-pro`（多步推理） | `deepseek-reasoner` | 多步推理（需 R1 推理能力） |

---

## 4. 整体架构

### 4.1 4 层架构图

```
┌─────────────────────────────────────────────────────────┐
│  Vue 3 前端 (frontend/)                                  │
│  - 聊天界面 (SSE 流式渲染)                                │
│  - 会话列表 (新建/删除/切换)                              │
│  - Markdown + 引用来源展示                               │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP + SSE
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI 服务层 (backend/app/api/)                       │
│  - POST /api/chat        (流式对话, SSE)                 │
│  - GET  /api/conversations (会话列表)                    │
│  - DELETE /api/conversations/{id}                        │
│  - POST /api/index/rebuild (重建索引)                    │
│  - GET  /api/health (健康检查)                           │
└──────────────────────┬──────────────────────────────────┘
                       │ 调用
┌──────────────────────▼──────────────────────────────────┐
│  LangGraph 编排层 (backend/app/graph/)                   │
│  - StateGraph: 8 个节点的状态机                          │
│  - 工具化抽象: call_llm / evaluate / retrieve / search   │
│  - 会话状态管理                                           │
└──────────┬───────────────────────────┬──────────────────┘
           │                           │
┌──────────▼─────────────┐  ┌──────────▼──────────────────┐
│  LlamaIndex RAG 层     │  │  外部工具                    │
│  (backend/app/rag/)    │  │  - DeepSeek API (LLM)       │
│  - ObsidianMarkdownReader │  │  - Tavily API (搜索)         │
│  - Chroma 向量库        │  │  - 华为云 MaaS (Embed/Rerank)│
│  - 检索 + Reranking     │  │                              │
└────────────────────────┘  └─────────────────────────────┘
```

### 4.2 项目目录结构

```
d:\Project\Agent\
├── backend/
│   ├── app/
│   │   ├── api/                  # FastAPI 路由
│   │   │   ├── chat.py           # 对话接口 (SSE)
│   │   │   ├── conversations.py  # 会话管理接口
│   │   │   ├── index.py          # 索引管理接口
│   │   │   ├── health.py         # 健康检查
│   │   │   └── errors.py         # 错误处理
│   │   ├── graph/                # LangGraph 编排层
│   │   │   ├── state.py          # 状态定义 (TypedDict)
│   │   │   ├── nodes.py          # 8 个节点函数
│   │   │   ├── tools.py          # 工具化抽象
│   │   │   ├── prompts.py        # 提示词模板（从 DSL 提取）
│   │   │   └── builder.py        # 图构建 + 编译
│   │   ├── rag/                  # LlamaIndex RAG 层
│   │   │   ├── indexer.py        # 索引构建 + 持久化
│   │   │   ├── retriever.py      # 检索 + Reranking
│   │   │   └── readers.py        # Obsidian Markdown Reader
│   │   ├── models/               # 数据模型 (Pydantic)
│   │   │   └── schemas.py
│   │   ├── services/             # 业务服务
│   │   │   └── conversation_store.py  # SQLite 会话存储
│   │   ├── config.py             # 配置
│   │   └── main.py               # FastAPI 入口
│   ├── data/
│   │   ├── chroma/               # Chroma 持久化目录
│   │   └── agent.db              # SQLite 数据库
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── unit/
│   │   ├── integration/
│   │   └── e2e/
│   ├── .env.example
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   └── ChatView.vue
│   │   ├── components/
│   │   │   ├── AppHeader.vue
│   │   │   ├── ConversationSidebar.vue
│   │   │   ├── ConversationList.vue
│   │   │   ├── ChatPanel.vue
│   │   │   ├── MessageList.vue
│   │   │   ├── UserMessage.vue
│   │   │   ├── AssistantMessage.vue
│   │   │   ├── MarkdownRenderer.vue
│   │   │   ├── StageIndicator.vue
│   │   │   ├── SourceCard.vue
│   │   │   ├── JudgeBadges.vue
│   │   │   └── InputBox.vue
│   │   ├── api/
│   │   │   ├── chat.ts           # SSE 客户端
│   │   │   └── conversations.ts
│   │   ├── stores/
│   │   │   └── chat.ts           # Pinia 状态
│   │   ├── types/
│   │   │   └── index.ts
│   │   ├── App.vue
│   │   └── main.ts
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── tsconfig.json
├── data/
│   └── raw -> D:\Project\Self-RAG-Agent\data\raw  # 软链
├── docs/
│   └── superpowers/specs/
│       └── 2026-07-26-xuai-agent-design.md
└── README.md
```

### 4.3 关键决策记录

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 会话存储 | SQLite（不是内存） | 修正"内存+会话管理"矛盾，依然零配置 |
| 知识库路径 | 软链到 `D:\Project\Self-RAG-Agent\data\raw` | 不复制原文件，保持单一数据源 |
| 流式协议 | SSE（不是 WebSocket） | 单向流足够，浏览器原生支持 |
| 前端状态 | Pinia | Vue 3 标配 |
| LangGraph 编排方案 | 方案 C：工具化抽象 | DRY、可扩展、易测试 |
| 前端 UI | Tailwind + 自写组件 | 聊天界面定制化高，组件库反而掣肘 |

---

## 5. LangGraph 编排层详细设计

### 5.1 状态定义

```python
# backend/app/graph/state.py
from typing import TypedDict, Optional, Annotated
from operator import add

class JudgeResult(TypedDict):
    judge_type: str        # "is_relevant" | "is_quality_pass" | "is_hallucination"
    passed: bool
    raw_output: dict

class AgentState(TypedDict):
    # 输入
    query: str                          # 用户原始问题
    conversation_id: str                # 会话 ID
    history: list[dict]                 # 历史对话 [{role, content}]

    # 中间产物
    rewritten_query: str                # 改写后的 query（用于检索/搜索）
    needs_decomposition: bool           # 是否需要多步推理
    reasoning_steps: list[dict]         # 分解出的子问题
    reasoning_result: str               # 多步推理结果

    is_relevant: Optional[bool]         # 知识库相关性
    retrieval_result: list[dict]        # 检索到的文档片段
    rag_quality_pass: Optional[bool]    # RAG 质量评估
    web_search_result: str              # Tavily 搜索结果
    local_answer: str                   # 知识库生成答案
    online_answer: str                  # 联网生成答案
    hallucination_flag: Optional[bool]  # 幻觉检测（true 表示有幻觉）
    answer_quality_pass: Optional[bool] # 答案质量评估

    # 输出
    final_answer: str                   # 最终回复
    route_path: str                     # 走的路径（调试用）

    # 评估日志（append 模式）
    judge_log: Annotated[list[JudgeResult], add]
```

**设计要点**：
- `judge_log` 用 `add` reducer，记录所有评估结果留痕
- 判断字段独立成字段，方便条件路由读取
- `route_path` 是调试字段，记录走了 `local` / `online` / `decomposition` / `fallback`

### 5.2 主图结构（8 个节点 + 1 个兜底）

**关键修正**：RAG 质量评估在生成**之前**（检索质量不行就不生成、直接转联网），幻觉检测和答案质量评估在生成**之后**。两者不能合并到一个 quality_gate 节点。

```
                          ┌─────────────────────────┐
                          │  START                  │
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │  1. rewrite_query       │  Query Rewrite
                          └────────────┬────────────┘
                                       │
                          ┌────────────▼────────────┐
                          │  2. decompose_question  │  问题分解判断
                          └────────────┬────────────┘
                                       │
                              needs_decomposition?
                            ┌──────────┴──────────┐
                       true │                  false│
                ┌───────────▼──────────┐  ┌─────────▼─────────┐
                │ 3. multi_step_reason │  │ 4. judge_relevance │
                └───────────┬──────────┘  └─────────┬─────────┘
                            │                       │ is_relevant?
                            │             ┌─────────┴─────────┐
                            │        true │              false│
                            │   ┌─────────▼─────────┐  ┌──────▼──────────┐
                            │   │ 5. rag_retrieve   │  │ 6. web_search   │
                            │   │  (检索+RAG质量评估) │  │   (Tavily)      │
                            │   └─────────┬─────────┘  └──────┬──────────┘
                            │             │                   │
                            │       rag_quality_pass?         │
                            │       ┌─────┴─────┐             │
                            │  true │       false│            │
                            │       │           └─► (转 web_search)
                            │   ┌───▼─────────────┐           │
                            │   │ 7. generate_answer│◄────────┘
                            │   └─────────┬─────────┘
                            │             │
                            │   ┌─────────▼─────────┐
                            │   │ 8. quality_gate   │  幻觉+答案质量（生成后）
                            │   └─────────┬─────────┘
                            │             │ quality_pass?
                            │       ┌─────┴─────┐
                            │  true │       false│
                            │       │   ┌────────▼────────┐
                            │       │   │ fallback_online │  兜底转联网
                            │       │   └────────┬────────┘
                            │       │            │
                            └───────┴────────────┘
                                       │
                                 ┌─────▼─────┐
                                 │   END     │
                                 └───────────┘
```

### 5.3 节点职责（含 Dify 节点映射）

| # | LangGraph 节点 | 对应 Dify 节点 ID | 职责 | 调用工具 |
|---|----------------|-------------------|------|----------|
| 1 | `rewrite_query` | `1784708937350` | 改写用户问题 | `call_llm(prompt=REWRITE_PROMPT, temp=0.7)` |
| 2 | `decompose_question` | `1785059627106` | 判断是否需要多步推理 | `call_llm(prompt=DECOMPOSE_PROMPT, schema=DecomposeSchema, temp=0.3)` |
| 3 | `multi_step_reason` | `1785059818901` | 多步推理执行 + 输出最终答案 | `call_llm(prompt=MULTI_STEP_PROMPT, temp=0.5, model=deepseek-reasoner)` |
| 4 | `judge_relevance` | `1785000000001` | 判断问题是否与知识库相关 | `evaluate("is_relevant", query)` |
| 5 | `rag_retrieve` | `1784562227367` + `1785100000001` | **检索 + RAG 质量评估**（生成前判断） | `retrieve(rewritten_query)` + `evaluate("is_quality_pass", retrieval_result)` |
| 6 | `web_search` | `1784709583735` | Tavily 搜索 | `tavily_search(rewritten_query)` |
| 7 | `generate_answer` | `1784711392079` + `1784713973176` | 统一生成节点：根据 route_path 选提示词 | `call_llm(prompt=按路由选, temp=0.7)` |
| 8 | `quality_gate` | `1785054451820`/`1785054783773` + `1785057290442`/`1785057355894` | **生成后评估**：幻觉检测 + 答案质量 | `evaluate(judge_type=...)` x2 |
| - | `fallback_online` | （新加） | 答案质量不通过时兜底：转 web_search + generate_answer | 复用 6+7 |

**重要**：`rag_retrieve` 节点同时做检索和 RAG 质量评估。检索完立即评估，若 `is_quality_pass=false` 则不进入 `generate_answer`，直接路由到 `web_search`。这对应 DSL 中 `1785100000002` (RAG 质量分支) 的 false 分支。

### 5.4 条件路由

```python
def route_after_decompose(state: AgentState) -> str:
    if state["needs_decomposition"]:
        return "multi_step_reason"
    return "judge_relevance"

def route_after_relevance(state: AgentState) -> str:
    return "rag_retrieve" if state["is_relevant"] else "web_search"

def route_after_rag_retrieve(state: AgentState) -> str:
    """RAG 质量评估决定是否继续生成。"""
    if state["rag_quality_pass"]:
        return "generate_answer"
    return "web_search"  # 检索质量不行，转联网

def route_after_quality(state: AgentState) -> str:
    """生成后质量门控：通过则结束，否则走兜底。"""
    if state["answer_quality_pass"] and not state["hallucination_flag"]:
        return END
    if state["route_path"] == "local":
        return "fallback_online"  # 知识库答案失败，兜底转联网
    return END  # 联网答案也失败，输出兜底文案
```

### 5.5 工具化抽象

```python
# backend/app/graph/tools.py
from typing import Optional
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

def call_llm(
    system_prompt: str,
    user_input: str,
    temperature: float = 0.3,
    output_schema: Optional[type[BaseModel]] = None,
    history: list[dict] = None,
    model: str = "deepseek-chat",
) -> dict:
    """统一 LLM 调用工具。
    - output_schema 非 None 时启用 structured output
    - history 非 None 时拼接到消息
    - 返回 {"text": str, "structured": dict|None}
    """
    ...

def evaluate(
    judge_type: str,  # "is_relevant" | "is_quality_pass" | "is_hallucination"
    source: str,      # 检索结果或搜索结果
    answer: str = "", # 待评估的答案
    query: str = "",
) -> JudgeResult:
    """统一评估工具。
    - 根据 judge_type 选提示词模板
    - 全部用 temp=0.2（修复温度不一致问题）
    - 全部用 structured output 强制 JSON
    - 返回 {judge_type, passed, raw_output}
    """
    ...

def retrieve(query: str, top_k: int = 3) -> list[dict]:
    """LlamaIndex 检索 + 华为云 bge-reranker-v2-m3 重排。"""
    ...

def tavily_search(query: str, max_results: int = 5) -> str:
    """Tavily 搜索。"""
    ...
```

### 5.6 修复点落地映射

| 修复项 | 实现方式 |
|--------|----------|
| 多步推理分支断裂 | `multi_step_reason` 节点直接写 `final_answer`，主图连到 END |
| 评估温度不一致 | `evaluate()` 工具统一硬编码 `temp=0.2` |
| 检索/生成 query 不一致 | `generate_answer` 节点用 `state["rewritten_query"]` |
| RAG 质量差回退（生成前） | `rag_retrieve` 节点内做质量评估，`route_after_rag_retrieve` 不通过则转 `web_search` |
| 答案质量不通过回退（生成后） | `fallback_online` 子路径转 web_search 重新生成（仅 `route_path=local` 时触发） |
| 重复 answer 节点 | 合并为 `generate_answer` 单节点，按 `route_path` 选提示词 |

---

## 6. LlamaIndex RAG 层详细设计

### 6.1 Obsidian Markdown Reader

```python
# backend/app/rag/readers.py
from llama_index.core.readers import MarkdownReader
from llama_index.core.schema import Document
import re
import frontmatter

class ObsidianMarkdownReader(MarkdownReader):
    """Obsidian .md 文件读取器。
    
    处理 Obsidian 特有语法：
    - frontmatter (YAML 元数据)
    - wikilink [[笔记名]]  → 转纯文本
    - callout > [!note] / > [!warning] 等 → 转普通引用
    - 标签 #tag  → 保留为纯文本
    - 内嵌 ![[图片.png]]  → 移除
    """

    def load_data(self, file_path, extra_info=None):
        post = frontmatter.load(file_path)
        content = post.content
        metadata = dict(post.metadata)
        
        content = self._strip_wikilinks(content)
        content = self._strip_callouts(content)
        content = self._strip_embeds(content)
        
        extra_info = extra_info or {}
        extra_info.update({
            "file_name": file_path.name,
            "title": metadata.get("title", file_path.stem),
            "tags": metadata.get("tags", []),
            "source": str(file_path),
        })
        
        return super().load_data_from_string(content, extra_info=extra_info)

    def _strip_wikilinks(self, text: str) -> str:
        return re.sub(r'\[\[([^\]]+)(?:\|([^\]]+))?\]\]',
                      lambda m: m.group(2) or m.group(1), text)

    def _strip_callouts(self, text: str) -> str:
        return re.sub(r'^>\s*\[!\w+\]\s*', '> ', text, flags=re.MULTILINE)

    def _strip_embeds(self, text: str) -> str:
        return re.sub(r'!\[\[[^\]]+\]\]', '', text)
```

### 6.2 索引构建

```python
# backend/app/rag/indexer.py
from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb
from pathlib import Path

class Indexer:
    """索引构建器。
    
    用法：
        indexer = Indexer(data_dir="data/raw", persist_dir="backend/data/chroma")
        indexer.load_or_build()  # 启动时调用
        indexer.build()          # 全量重建
        indexer.update("RAG.md") # 增量更新
    """
    
    def __init__(self, data_dir: str, persist_dir: str):
        self.data_dir = Path(data_dir)
        self.persist_dir = Path(persist_dir)
        
        Settings.embed_model = HuaweiEmbedding(
            model="bge-large-zh-v1.5",
            api_key=settings.HUAWEI_API_KEY,
        )
        Settings.chunk_size = 512
        Settings.chunk_overlap = 50
        
        self.db = chromadb.PersistentClient(path=str(self.persist_dir))
        self.chroma_collection = self.db.get_or_create_collection("obsidian_kb")
        self.vector_store = ChromaVectorStore(chroma_collection=self.chroma_collection)
        self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
    
    def build(self):
        reader = ObsidianMarkdownReader()
        documents = []
        for md_file in self.data_dir.glob("*.md"):
            documents.extend(reader.load_data(file_path=md_file))
        
        self.index = VectorStoreIndex.from_documents(
            documents,
            storage_context=self.storage_context,
            show_progress=True,
        )
    
    def load_or_build(self):
        try:
            self.index = VectorStoreIndex.from_vector_store(
                self.vector_store,
                storage_context=self.storage_context,
            )
        except Exception:
            self.build()
    
    def update(self, file_name: str):
        self.chroma_collection.delete(where={"file_name": file_name})
        reader = ObsidianMarkdownReader()
        file_path = self.data_dir / file_name
        if file_path.exists():
            docs = reader.load_data(file_path=file_path)
            for doc in docs:
                self.index.insert(doc)
    
    def get_retriever(self):
        return RAGRetriever(self.index, top_k=3)
```

### 6.3 检索 + Reranking

```python
# backend/app/rag/retriever.py
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore

class HuaweiReranker(BaseNodePostprocessor):
    """华为云 MaaS bge-reranker-v2-m3 重排器。
    
    对应 DSL 配置：
    - reranking_model: bge-reranker-v2-m3
    - provider: langgenius/maas/huaweicloud_maas
    """
    
    @classmethod
    def class_name(cls) -> str:
        return "HuaweiReranker"
    
    def _postprocess_nodes(
        self, nodes: list[NodeWithScore], query_str: str = None
    ) -> list[NodeWithScore]:
        if not nodes:
            return []
        texts = [node.node.get_content() for node in nodes]
        rerank_result = self._call_huawei_rerank(query_str, texts)
        for node, score in zip(nodes, rerank_result["scores"]):
            node.score = score
        return sorted(nodes, key=lambda x: x.score or 0, reverse=True)
    
    def _call_huawei_rerank(self, query: str, documents: list[str]) -> dict:
        # 实现华为云 MaaS rerank 接口调用
        ...


class RAGRetriever:
    """统一检索器：向量检索 + Reranking。
    
    对应 DSL 节点 1784562227367 (knowledge-retrieval)：
    - top_k: 3
    - reranking_enable: true
    - reranking_model: bge-reranker-v2-m3
    """
    
    def __init__(self, index, top_k: int = 3):
        self.retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=top_k * 3,  # 初检召回 3 倍
        )
        self.reranker = HuaweiReranker()
        self.final_top_k = top_k
    
    def retrieve(self, query: str) -> list[dict]:
        # 1. 向量初检（召回 top_k * 3）
        nodes = self.retriever.retrieve(query)
        # 2. Reranking 精排
        reranked = self.reranker.postprocess_nodes(nodes, query_str=query)
        # 3. 取最终 top_k
        final = reranked[:self.final_top_k]
        # 4. 格式化输出
        return [
            {
                "content": node.node.get_content(),
                "source": node.node.metadata.get("file_name", "未知"),
                "title": node.node.metadata.get("title", ""),
                "score": node.score or 0,
            }
            for node in final
        ]
```

### 6.4 数据流示例

走知识库路径（用户问「Agent 和 Workflow 有什么区别？」）：

```
用户输入: "Agent 和 Workflow 有什么区别？"
│
├─► [FastAPI /api/chat] POST {conversation_id, message}
│    创建 LangGraph run，开启 SSE 流
│
├─► [节点 1: rewrite_query]
│    输入: query="Agent 和 Workflow 有什么区别？"
│    调用: call_llm(REWRITE_PROMPT, query, temp=0.7)
│    输出: rewritten_query="Agent 与 Workflow 在定义、核心特征、应用场景上的区别"
│
├─► [节点 2: decompose_question]
│    调用: call_llm(DECOMPOSE_PROMPT, schema, temp=0.3)
│    输出: {needs_decomposition: false, ...}
│
├─► [节点 4: judge_relevance]
│    调用: evaluate("is_relevant", query)
│    输出: is_relevant=true
│
├─► [节点 5: rag_retrieve]
│    ├─ 调用: retrieve("Agent 与 Workflow 在定义...", top_k=3)
│    │   输出: [{content, source: "Agent.md", score}, ...]
│    └─ 调用: evaluate("is_quality_pass", retrieval_result) temp=0.2
│        输出: rag_quality_pass=true
│
├─► [路由 route_after_rag_retrieve]
│    rag_quality_pass=true → generate_answer
│
├─► [节点 7: generate_answer]
│    route_path ← "local"
│    调用: call_llm(LOCAL_GEN_PROMPT, temp=0.7)
│    输出: local_answer="Agent 是...Workflow 是..."
│
├─► [节点 8: quality_gate]
│    ├─ evaluate("is_hallucination", retrieval_result, local_answer) temp=0.2
│    ├─ evaluate("is_quality_pass", answer=local_answer) temp=0.2
│    输出: hallucination_flag=false, answer_quality_pass=true
│
└─► [FastAPI SSE 返回]
     data: {"type": "stage", "data": "正在检索知识库..."}
     data: {"type": "token", "data": "Agent 是..."}
     data: {"type": "meta", "data": {"route_path": "local", "sources": [...]}}
     data: {"type": "done"}
```

**RAG 质量不通过的分支**（检索结果与问题无关时）：

```
├─► [节点 5: rag_retrieve]
│    ├─ retrieve(...) → [{content, score: 0.12}, ...]  (分数低)
│    └─ evaluate("is_quality_pass") → rag_quality_pass=false
│
├─► [路由 route_after_rag_retrieve]
│    rag_quality_pass=false → web_search
│
├─► [节点 6: web_search]
│    ...（走联网分支，与原始 DSL 一致）
```

---

## 7. FastAPI 服务层详细设计

### 7.1 API 端点清单

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/chat` | 流式对话 | `{conversation_id, message}` | SSE 流 |
| GET | `/api/conversations` | 会话列表 | - | `[{id, title, created_at, updated_at, message_count}]` |
| POST | `/api/conversations` | 新建会话 | `{title?}` | `{id, title, created_at}` |
| GET | `/api/conversations/{id}` | 会话详情 | - | `{id, title, messages: [...]}` |
| DELETE | `/api/conversations/{id}` | 删除会话 | - | `{success: bool}` |
| PATCH | `/api/conversations/{id}` | 重命名 | `{title}` | `{id, title}` |
| POST | `/api/index/rebuild` | 重建索引 | - | `{success, doc_count}` |
| GET | `/api/health` | 健康检查 | - | `{status, model, vector_db, embedding_model}` |

### 7.2 SQLite Schema

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '新会话',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    message_count INTEGER DEFAULT 0
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,            -- 'user' | 'assistant'
    content TEXT NOT NULL,
    route_path TEXT,
    sources TEXT,                  -- JSON
    judge_log TEXT,                -- JSON
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);
```

### 7.3 Pydantic 模型

```python
# backend/app/models/schemas.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal

class ChatRequest(BaseModel):
    conversation_id: str
    message: str = Field(..., min_length=1, max_length=2000)

class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=100)

class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)

class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int

class MessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    route_path: Optional[str] = None
    sources: Optional[list[dict]] = None
    judge_log: Optional[list[dict]] = None
    created_at: datetime

class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]

class IndexRebuildResponse(BaseModel):
    success: bool
    doc_count: int

class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    model: str
    vector_db: str
    embedding_model: str
```

### 7.4 会话存储服务

```python
# backend/app/services/conversation_store.py
import aiosqlite
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Optional

class ConversationStore:
    """SQLite 异步会话存储。"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()
    
    async def create_conversation(self, title: Optional[str] = None) -> str: ...
    async def list_conversations(self) -> list[dict]: ...
    async def get_conversation(self, conv_id: str) -> Optional[dict]: ...
    async def add_message(self, conv_id, role, content, route_path=None,
                          sources=None, judge_log=None) -> str: ...
    async def delete_conversation(self, conv_id: str) -> bool: ...
    async def update_conversation_title(self, conv_id, title) -> bool: ...
    async def get_history(self, conv_id: str, limit: int = 10) -> list[dict]:
        """获取最近 N 轮历史，对应 DSL memory.window.size=10。"""
        ...
```

### 7.5 流式对话接口

```python
# backend/app/api/chat.py
@router.post("")
async def chat_stream(
    body: ChatRequest,
    store: ConversationStore = Depends(get_store),
    graph=Depends(get_graph),
):
    conv = await store.get_conversation(body.conversation_id)
    if not conv:
        raise HTTPException(404, "会话不存在")
    
    await store.add_message(body.conversation_id, role="user", content=body.message)
    history = await store.get_history(body.conversation_id, limit=10)
    
    input_state = {
        "query": body.message,
        "conversation_id": body.conversation_id,
        "history": history[:-1],
        "judge_log": [],
    }
    
    async def event_generator():
        final_state = None
        try:
            async for event in graph.astream_events(input_state, version="v2"):
                if event["event"] == "on_chain_start":
                    node_name = event["name"]
                    stage_text = STAGE_LABELS.get(node_name, f"执行: {node_name}")
                    yield {"event": "message", "data": json.dumps({
                        "type": "stage", "data": stage_text
                    })}
                elif event["event"] == "on_llm_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        yield {"event": "message", "data": json.dumps({
                            "type": "token", "data": chunk.content
                        })}
                elif event["event"] == "on_chain_end" and event["name"] == "LangGraph":
                    final_state = event["data"]["output"]
            
            if final_state:
                await store.add_message(
                    body.conversation_id,
                    role="assistant",
                    content=final_state.get("final_answer", ""),
                    route_path=final_state.get("route_path"),
                    sources=final_state.get("retrieval_result"),
                    judge_log=final_state.get("judge_log", []),
                )
                yield {"event": "message", "data": json.dumps({
                    "type": "meta",
                    "data": {
                        "route_path": final_state.get("route_path"),
                        "sources": final_state.get("retrieval_result", []),
                        "judge_log": final_state.get("judge_log", []),
                    }
                })}
            yield {"event": "message", "data": json.dumps({"type": "done"})}
        except Exception as e:
            logger.exception("对话流式失败")
            yield {"event": "message", "data": json.dumps({
                "type": "error",
                "data": {"message": ERROR_MESSAGES.get(type(e).__name__, "服务内部错误")}
            })}
            yield {"event": "message", "data": json.dumps({"type": "done"})}
    
    return EventSourceResponse(event_generator())

STAGE_LABELS = {
    "rewrite_query": "正在理解问题...",
    "decompose_question": "正在分析问题结构...",
    "multi_step_reason": "正在进行多步推理...",
    "judge_relevance": "正在判断问题类型...",
    "rag_retrieve": "正在检索知识库...",
    "web_search": "正在联网搜索...",
    "generate_answer": "正在生成回答...",
    "quality_gate": "正在评估答案质量...",
    "fallback_online": "正在尝试联网搜索...",
}
```

### 7.6 错误处理策略

#### 错误码映射

```python
ERROR_MESSAGES = {
    "AuthenticationError": "AI 服务认证失败，请检查 API Key 配置",
    "RateLimitError": "AI 服务调用频率过高，请稍后重试",
    "APIConnectionError": "无法连接到 AI 服务",
    "Timeout": "AI 服务响应超时",
    "ChromaError": "知识库检索失败，可能是索引损坏",
    "EmbeddingError": "向量化服务调用失败",
    "RerankerError": "重排服务调用失败",
    "TavilyError": "联网搜索服务调用失败",
    "OperationalError": "数据库操作失败",
    "ValidationError": "请求参数无效",
}

ERROR_STATUS_CODE = {
    "AuthenticationError": 503,
    "RateLimitError": 429,
    "APIConnectionError": 502,
    "Timeout": 504,
    "ValidationError": 422,
}
```

#### 各层错误处理

| 层 | 错误类型 | 处理策略 |
|----|----------|----------|
| FastAPI | 请求参数错误 | Pydantic 自动 422 |
| FastAPI | 会话不存在 | 404 |
| LangGraph | LLM 调用失败 | 节点抛异常 → 流中断 → SSE 返回 error |
| LangGraph | 评估节点 JSON 解析失败 | 重试 1 次，仍失败则默认 `passed=false`，走兜底 |
| LangGraph | 检索为空 | 不抛异常，正常走 quality_gate，自然转 fallback |
| LangGraph | Tavily 失败 | 抛异常，SSE 返回 error |
| RAG | 索引不存在 | 启动时 `load_or_build()` 自动构建 |
| SQLite | 写入失败 | 抛异常，FastAPI 统一 500 |

#### 质量门控节点容错

`quality_gate` 节点只做生成后两步评估（幻觉 + 答案质量），RAG 质量评估在 `rag_retrieve` 节点内完成。

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=True)
async def quality_gate_node(state: AgentState) -> dict:
    """生成后质量门控：幻觉检测 + 答案质量评估。"""
    try:
        source = (state["retrieval_result"] if state["route_path"] == "local"
                  else state["web_search_result"])
        answer = (state["local_answer"] if state["route_path"] == "local"
                  else state["online_answer"])

        # 1. 幻觉检测
        halluc_judge = await evaluate(
            judge_type="is_hallucination",
            source=source, answer=answer, query=state["rewritten_query"],
        )
        state["hallucination_flag"] = halluc_judge["passed"]
        state["judge_log"] = [halluc_judge]

        # 2. 答案质量评估
        quality_judge = await evaluate(
            judge_type="is_quality_pass",
            source=source, answer=answer, query=state["rewritten_query"],
        )
        state["answer_quality_pass"] = quality_judge["passed"]
        state["judge_log"] = [quality_judge]

        # 综合：质量通过 = 无幻觉 AND 答案质量通过
        state["answer_quality_pass"] = (
            not state["hallucination_flag"] and state["answer_quality_pass"]
        )
        return state
    except Exception as e:
        logger.warning(f"质量门控失败，降级到不通过: {e}")
        state["answer_quality_pass"] = False
        state["hallucination_flag"] = True
        state["judge_log"] = [{
            "judge_type": "fallback",
            "passed": False,
            "raw_output": {"error": str(e)},
        }]
        return state
```

### 7.7 配置管理

```python
# backend/app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # === LLM (DeepSeek) ===
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    
    # === Embedding & Reranker (华为云 MaaS) ===
    HUAWEI_API_KEY: str
    HUAWEI_BASE_URL: str = "https://maas.cn-north-4.myhuaweicloud.com"
    EMBEDDING_MODEL: str = "bge-large-zh-v1.5"
    RERANKER_MODEL: str = "bge-reranker-v2-m3"
    
    # === Tavily ===
    TAVILY_API_KEY: str
    
    # === 知识库 ===
    KB_DATA_DIR: str = r"D:\Project\Self-RAG-Agent\data\raw"
    CHROMA_PERSIST_DIR: str = "backend/data/chroma"
    
    # === SQLite ===
    SQLITE_PATH: str = "backend/data/agent.db"
    
    # === CORS ===
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:4173"]
    
    # === 模型映射 ===
    MODEL_FLASH: str = "deepseek-chat"
    MODEL_PRO_CHAT: str = "deepseek-chat"
    MODEL_PRO_REASON: str = "deepseek-reasoner"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

### 7.8 .env.example

```env
# DeepSeek API
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 华为云 MaaS (Embedding + Reranker)
HUAWEI_API_KEY=xxxxxxxxxxxxxxxx

# Tavily Search
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx

# 知识库目录（可覆盖默认值）
KB_DATA_DIR=D:\Project\Self-RAG-Agent\data\raw
```

### 7.9 启动流程

```python
# backend/app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _store, _indexer, _graph
    
    # 1. 初始化会话存储
    _store = ConversationStore(settings.SQLITE_PATH)
    await _store.init()
    
    # 2. 初始化 RAG 索引
    _indexer = Indexer(
        data_dir=settings.KB_DATA_DIR,
        persist_dir=settings.CHROMA_PERSIST_DIR,
    )
    _indexer.load_or_build()  # 首次启动会构建索引
    
    # 3. 构建 LangGraph
    _graph = build_graph(retriever=_indexer.get_retriever())
    
    yield
```

---

## 8. Vue 3 前端详细设计

### 8.1 前端技术栈

| 类别 | 选型 | 理由 |
|------|------|------|
| 框架 | Vue 3 + `<script setup>` + TypeScript | 用户已熟悉 |
| 构建 | Vite 5 | Vue 3 标配 |
| 状态 | Pinia | Vue 3 官方推荐 |
| 路由 | Vue Router 4 | 单页应用 |
| UI 组件 | 不用组件库（自写） | 聊天界面定制化高 |
| 样式 | Tailwind CSS 3 | 原子 CSS |
| Markdown | markdown-it + highlight.js | 生态全 |
| HTTP | fetch + ReadableStream | SSE 手动解析 |
| 图标 | lucide-vue-next | 轻量 |

### 8.2 页面结构

```
路由：
/                → 重定向到 /chat/{最新会话}
/chat/:id        → ChatView
```

```
┌─────────────────────────────────────────────────────────────┐
│  顶部 Header (h-14)                                          │
│  [🤖 学AI必备助手]    [状态: DeepSeek API ✓]    [设置 ⚙️]   │
├──────────────┬──────────────────────────────────────────────┤
│  左侧栏       │  主对话区                                    │
│  (w-72)      │                                              │
│  [+ 新会话]   │  消息列表（滚动区）                           │
│  会话列表     │  [用户气泡 - 右对齐]                          │
│              │  [助手气泡 - 左对齐 + Markdown]                │
│              │    正在检索知识库... (stage)                  │
│              │    [流式 token 光标]                         │
│              │    [来源: Agent.md] [评估: ✓ 通过]           │
│              │  输入区 (textarea + Ctrl+Enter 发送)         │
└──────────────┴──────────────────────────────────────────────┘
```

### 8.3 组件树

```
App.vue
└── ChatView.vue
    ├── AppHeader.vue
    ├── ConversationSidebar.vue
    │   ├── NewConversationButton.vue
    │   └── ConversationList.vue
    │       └── ConversationItem.vue
    ├── ChatPanel.vue
    │   ├── MessageList.vue
    │   │   ├── UserMessage.vue
    │   │   └── AssistantMessage.vue
    │   │       ├── MarkdownRenderer.vue
    │   │       ├── StageIndicator.vue
    │   │       ├── SourceCard.vue
    │   │       └── JudgeBadges.vue
    │   └── InputBox.vue
    └── EmptyState.vue
```

### 8.4 SSE 客户端

```typescript
// frontend/src/api/chat.ts
interface StreamCallbacks {
  onStage: (stage: string) => void
  onToken: (token: string) => void
  onMeta: (meta: { route_path: string; sources: any[]; judge_log: any[] }) => void
  onError: (message: string) => void
  onDone: () => void
}

export async function streamChat(req: ChatRequest, cb: StreamCallbacks) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })

  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  if (!response.body) throw new Error('No response body')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''

    for (const eventStr of events) {
      const lines = eventStr.split('\n')
      let dataLine = ''
      for (const line of lines) {
        if (line.startsWith('data:')) dataLine += line.slice(5).trim()
      }
      if (!dataLine) continue

      try {
        const payload = JSON.parse(dataLine)
        switch (payload.type) {
          case 'stage': cb.onStage(payload.data); break
          case 'token': cb.onToken(payload.data); break
          case 'meta': cb.onMeta(payload.data); break
          case 'error': cb.onError(payload.data.message); break
          case 'done': cb.onDone(); return
        }
      } catch (e) {
        console.error('SSE parse error:', e, dataLine)
      }
    }
  }
}
```

### 8.5 Pinia Store

```typescript
// frontend/src/stores/chat.ts
export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const isStreaming = ref(false)
  const inputText = ref('')
  const error = ref<string | null>(null)

  async function loadConversations() { ... }
  async function createConversation() { ... }
  async function selectConversation(id: string) { ... }
  async function deleteConversation(id: string) { ... }
  
  async function sendMessage() {
    if (!inputText.value.trim() || isStreaming.value) return
    if (!currentConversationId.value) await createConversation()

    const convId = currentConversationId.value!
    const userMsg: Message = { /* ... */ }
    const assistantMsg: Message = { isStreaming: true, currentStage: '准备中...', /* ... */ }
    messages.value.push(userMsg, assistantMsg)

    const messageText = inputText.value
    inputText.value = ''
    isStreaming.value = true

    try {
      await chatApi.streamChat(
        { conversation_id: convId, message: messageText },
        {
          onStage: (stage) => { assistantMsg.currentStage = stage },
          onToken: (token) => { assistantMsg.content += token },
          onMeta: (meta) => {
            assistantMsg.route_path = meta.route_path
            assistantMsg.sources = meta.sources
            assistantMsg.judge_log = meta.judge_log
          },
          onError: (errMsg) => {
            error.value = errMsg
            assistantMsg.content = `⚠️ ${errMsg}`
          },
          onDone: () => {
            assistantMsg.isStreaming = false
            assistantMsg.currentStage = undefined
            isStreaming.value = false
          },
        }
      )
    } catch (e: any) {
      error.value = e.message || '网络错误'
      assistantMsg.isStreaming = false
      isStreaming.value = false
    }
  }

  return { conversations, currentConversationId, messages, isStreaming, inputText, error,
           loadConversations, createConversation, selectConversation, deleteConversation, sendMessage }
})
```

### 8.6 关键组件

#### AssistantMessage

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { Message } from '@/stores/chat'
import MarkdownRenderer from './MarkdownRenderer.vue'
import StageIndicator from './StageIndicator.vue'
import SourceCard from './SourceCard.vue'
import JudgeBadges from './JudgeBadges.vue'

const props = defineProps<{ message: Message }>()

const routeLabel = computed(() => ({
  local: '知识库', online: '联网搜索',
  decomposition: '多步推理', fallback: '兜底回复',
}[props.message.route_path || ''] || ''))
</script>

<template>
  <div class="flex gap-3 px-4 py-3 group">
    <div class="flex-shrink-0 w-8 h-8 rounded-full bg-orange-100 flex items-center justify-center text-lg">🤖</div>
    <div class="flex-1 min-w-0">
      <StageIndicator v-if="message.isStreaming && message.currentStage" :text="message.currentStage" />
      <div v-if="message.content" class="prose prose-sm max-w-none">
        <MarkdownRenderer :content="message.content" />
        <span v-if="message.isStreaming" class="inline-block w-2 h-4 bg-gray-400 animate-pulse ml-0.5" />
      </div>
      <div v-if="message.sources?.length" class="mt-3 flex flex-wrap gap-2">
        <SourceCard v-for="(source, i) in message.sources" :key="i" :source="source" :index="i + 1" />
      </div>
      <div v-if="!message.isStreaming && message.route_path" class="mt-2 flex items-center gap-2 text-xs text-gray-500">
        <span v-if="routeLabel" class="px-2 py-0.5 rounded bg-gray-100">{{ routeLabel }}</span>
        <JudgeBadges v-if="message.judge_log?.length" :judges="message.judge_log" />
      </div>
    </div>
  </div>
</template>
```

### 8.7 流式输出三层协议

| 事件类型 | 数据 | 前端处理 |
|----------|------|----------|
| `stage` | `{type: "stage", data: "正在检索知识库..."}` | 显示阶段进度条 |
| `token` | `{type: "token", data: "Agent 是..."}` | 实时拼接到消息气泡（Markdown 实时渲染） |
| `meta` | `{type: "meta", data: {route_path, sources, judge_log}}` | 渲染引用来源卡片 + 评估标签 |
| `error` | `{type: "error", data: {message}}` | 显示错误提示 |
| `done` | `{type: "done"}` | 关闭流 |

---

## 9. 测试策略

### 9.1 后端测试

| 层 | 类型 | 工具 | 覆盖范围 |
|----|------|------|----------|
| RAG 层 | 单元测试 | pytest + pytest-asyncio | ObsidianMarkdownReader 语法清洗、Retriever 输出格式 |
| Graph 层 | 单元测试 | pytest + mock LLM | 8 个节点输入输出、条件路由 |
| API 层 | 集成测试 | pytest + httpx AsyncClient | 7 个端点 HTTP 状态码、响应结构 |
| 端到端 | 冒烟测试 | pytest + 真实 API | 3 条典型路径走通 |

#### 测试文件结构

```
backend/tests/
├── conftest.py                  # 公共 fixture
├── unit/
│   ├── test_readers.py          # ObsidianMarkdownReader
│   ├── test_retriever.py        # RAGRetriever
│   ├── test_nodes.py            # LangGraph 节点
│   ├── test_tools.py            # call_llm / evaluate
│   └── test_store.py            # ConversationStore
├── integration/
│   ├── test_api_chat.py         # /api/chat SSE 流
│   ├── test_api_conversations.py
│   └── test_api_index.py
└── e2e/
    ├── test_local_path.py
    ├── test_online_path.py
    └── test_decomposition_path.py
```

#### 关键测试用例

- `test_strip_wikilinks_simple`：`[[Agent]]` → `Agent`
- `test_strip_wikilinks_with_alias`：`[[Agent|智能体]]` → `智能体`
- `test_strip_callouts`：`> [!warning] 注意` → `> 注意`
- `test_strip_embeds`：`![[diagram.png]]` 移除
- `test_load_real_obsidian_file`：加载真实 .md，验证元数据
- `test_rewrite_query_node_calls_llm_with_correct_params`：验证改写节点 LLM 调用参数
- `test_quality_gate_node_fallback_on_error`：评估失败降级
- `test_chat_endpoint_returns_sse_stream`：SSE 流式响应

### 9.2 前端测试

| 类型 | 工具 | 覆盖范围 |
|------|------|----------|
| 单元测试 | Vitest | store 状态机、SSE 解析、Markdown 渲染 |
| 组件测试 | Vue Test Utils | 消息组件渲染、用户交互 |

前端测试范围较小（开发期），重点测：
- `streamChat` 的 SSE 解析正确性
- `chat` store 的状态流转
- `MarkdownRenderer` 不暴露 XSS

---

## 10. 安全考虑

| 风险 | 缓解措施 |
|------|----------|
| XSS（Markdown 渲染） | `markdown-it` 默认转义 HTML；关闭 `html: true`；`highlight.js` 只渲染代码块 |
| Prompt 注入 | 用户输入作为 LLM 的 user message；检索内容用 `<context>` 标签包裹 |
| API Key 泄露 | 后端 `.env` 不进 git；前端只调 `/api/*`，永远不直接调外部 API |
| CORS | 开发期允许 `localhost:5173`；生产环境配置具体域名 |
| 输入长度 | `ChatRequest.message` 限制 2000 字符 |
| SQL 注入 | 全部用参数化查询（`?` 占位符） |
| 会话越权 | 开发期不做用户系统；后续扩展时加 user_id 隔离 |

---

## 11. 部署形态

### 开发期（当前）

```
前端: vite dev → http://localhost:5173 (代理 /api → localhost:8000)
后端: uvicorn app.main:app --reload → http://localhost:8000
```

### 生产期（后续）

```
前端: vite build → 静态文件 → nginx 托管
后端: uvicorn + gunicorn worker → nginx 反代
知识库: 持久化在服务器磁盘
```

---

## 12. 关键设计权衡汇总

| 决策点 | 选择 | 反方论点 | 仍选此的理由 |
|--------|------|----------|-------------|
| LangGraph 编排方案 | 方案 C：工具化抽象 | DSL → 代码映射不直观 | 5 个评估节点 + 3 个 answer 节点重复严重，方案 A 会复制粘贴地狱 |
| Chunk 策略 | 按 header 分段 + 512 token 上限 | 固定 overlap 可能切断语义 | 18 篇笔记平均 < 2000 字，按 header 分段粒度合适 |
| Embedding 模型 | `bge-large-zh-v1.5` | bge-m3 多语言更全 | 笔记全中文，bge-large-zh-v1.5 中文效果更好 |
| Reranker 启用 | 启用 | 18 篇小知识库 reranker 收益有限 | DSL 原配置就启用，保持一致；top_k=3 时 reranker 显著提升 precision |
| 流式协议 | SSE 单向 | WebSocket 双向可中途取消 | SSE 浏览器原生支持，简单稳定；取消靠前端关连接 |
| 异步栈 | FastAPI + aiosqlite + async graph | LangGraph 异步 API 略不稳定 | 全异步栈吞吐量高，跟前端 SSE 配合顺畅 |
| SSE 库 | sse-starlette | FastAPI 原生 StreamingResponse 也能做 | sse-starlette 处理了断连、心跳、CORS |
| 数据库访问 | 原生 SQL + aiosqlite | SQLAlchemy ORM 更工程化 | 7 张表不值得上 ORM，原生 SQL 调试直观 |
| 错误暴露 | 不向用户暴露原始错误 | 调试时不方便 | 安全优先；详细错误到服务端日志 |
| 评估节点容错 | 失败降级到不通过 + 走兜底 | 隐藏评估节点真实问题 | 用户体验优先；评估失败降级比抛错好 |
| 前端 UI | Tailwind + 自写组件 | 组件库一致性更好 | 聊天界面 90% 自定义，组件库反而掣肘 |
| SSE 客户端 | fetch + ReadableStream | EventSource 更简单 | EventSource 不支持 POST，硬伤 |
| 前端测试 | Vitest 单元 | E2E Playwright 更全面 | 开发期 YAGNI；后端测试已覆盖核心 |
| Markdown 渲染 | markdown-it | marked 更轻量 | markdown-it 插件生态全 |
| 评估标签展示 | 红/绿 chip 展示 | 隐藏不展示给用户 | 开发期需要看到评估结果调优 |

---

## 13. 实现优先级（粗略）

实现阶段会通过 writing-plans 技能细化为任务清单，这里仅列出大阶段：

1. **环境搭建**：项目骨架、依赖、配置
2. **RAG 层**：ObsidianMarkdownReader + Indexer + Retriever（先跑通检索）
3. **Graph 层**：8 个节点 + 工具化抽象 + 图构建（先跑通单路径）
4. **API 层**：FastAPI 路由 + SSE 流式 + 错误处理
5. **前端**：Vue 3 骨架 + 聊天界面 + SSE 客户端
6. **测试**：单元 + 集成 + E2E
7. **联调优化**：3 条路径端到端验证

---

## 14. 验收标准

- [ ] 3 条主路径（知识库 / 联网 / 多步推理）端到端走通
- [ ] SSE 流式输出正常，前端实时渲染
- [ ] 会话管理（新建/切换/删除/重命名）正常
- [ ] 引用来源和评估标签正确展示
- [ ] 多步推理 bug 修复（用户能看到回复）
- [ ] 评估节点温度统一为 0.2
- [ ] 检索/生成使用同一 query
- [ ] RAG 质量不通过时走 fallback_online
- [ ] 后端单元测试覆盖率 ≥ 70%
- [ ] 前端核心组件有单元测试
- [ ] `.env.example` 完整，3 个 API Key 配置清晰
