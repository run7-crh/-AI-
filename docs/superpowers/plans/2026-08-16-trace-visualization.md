# 思考过程可视化（Trace Visualization）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在聊天界面嵌入类 LangSmith 的思考过程 trace：SSE 新增 `node_end`/`reasoning` 事件，前端 TraceTimeline 组件实时展示节点执行链路（含中间结果与 reasoner 思维流），完成后折叠为摘要行。

**Architecture:** 后端在现有 `astream_events` 事件循环上增量消费 `on_chain_end`（name=具体节点）与 chunk 的 `reasoning_content`，新增纯函数模块 `app/api/trace.py` 承载白名单/截断/提取逻辑（可单测）；前端沿 `chat.ts` dispatch → store 状态机 → `TraceTimeline.vue` 渲染的数据流，替代并删除 StageIndicator。

**Tech Stack:** FastAPI + sse-starlette（后端已存在）、Vue 3 + TS + Pinia + Tailwind + lucide-vue-next（前端已存在）、pytest / vitest（测试已存在）。零新增依赖。

**Spec:** `docs/superpowers/specs/2026-08-16-trace-visualization-design.md`（已评审通过）

**关键现状（避免踩坑）：**
- 后端事件循环在 `backend/app/api/chat.py:110-138`；`STAGE_LABELS` 定义于 `chat.py:54-68`，仅此一处使用。
- 现有 SSE data 均为 `{"type": ..., "data": ...}` JSON；`stage` 事件 data 当前是裸 string，本计划将其升级为 `{node, label}` 对象（breaking，前后端同仓库同步改）。
- chunk 兼容对象（`.content` 属性）与 dict（`"content"` 键）两种形态（`chat.py:123-130`），reasoning 提取需同样兼容。
- 前端 `MessageList.vue:22` watch `currentStage` 触发滚动，保留 `currentStage` 字段（存 label）以免破坏。
- `StreamCallbacks` 新增回调设为**可选**，避免改动所有现存调用点/测试。
- 前端测试命令 `npm run test`（vitest），后端 `python -m pytest backend/tests -x -q`（在仓库根执行；若虚拟环境在 backend 下则先激活）。

---

### Task 1: 后端 trace 纯函数模块（STAGE_LABELS 迁移 + 白名单 + 截断 + reasoning 提取）

**Files:**
- Create: `backend/app/api/trace.py`
- Create: `backend/tests/unit/test_trace.py`

- [ ] **Step 1: 写失败的单测**

创建 `backend/tests/unit/test_trace.py`：

```python
# backend/tests/unit/test_trace.py
"""trace 纯函数单测：白名单提取 / 截断 / reasoning 捞取。"""
from app.api.trace import (
    extract_reasoning_content,
    extract_trace_output,
    truncate_text,
)


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert truncate_text("短文本") == "短文本"

    def test_long_text_truncated_with_ellipsis(self):
        out = truncate_text("x" * 300)
        assert len(out) == 201  # 200 字 + 省略号
        assert out.endswith("…")

    def test_non_string_returned_as_is(self):
        assert truncate_text(123) == 123  # type: ignore[arg-type]


class TestExtractTraceOutput:
    def test_whitelist_filters_unknown_fields(self):
        output = {"rewritten_query": "什么是 RAG", "is_relevant": True, "judge_log": []}
        assert extract_trace_output("rewrite_query", output) == {
            "rewritten_query": "什么是 RAG"
        }

    def test_generate_nodes_return_empty(self):
        # 正文走 token 流，仅显示名称+耗时
        assert extract_trace_output(
            "generate_local", {"final_answer": "x", "route_path": "local"}
        ) == {}
        assert extract_trace_output("multi_step_reason", {"final_answer": "x"}) == {}
        assert extract_trace_output("chitchat_node", {"final_answer": "x"}) == {}
        assert extract_trace_output("generate_online", {"final_answer": "x"}) == {}

    def test_unknown_node_returns_empty(self):
        assert extract_trace_output("nonexistent_node", {"a": 1}) == {}

    def test_none_or_empty_output_returns_empty(self):
        assert extract_trace_output("rewrite_query", None) == {}
        assert extract_trace_output("rewrite_query", {}) == {}

    def test_truncates_retrieval_result_content(self):
        output = {
            "retrieval_result": [
                {"content": "x" * 300, "title": "RAG", "source": "a.md", "score": 0.9}
            ],
            "avg_reranker_score": 0.9,
        }
        result = extract_trace_output("rag_retrieve", output)
        assert len(result["retrieval_result"][0]["content"]) == 201
        assert result["avg_reranker_score"] == 0.9
        # 截断不改其他字段
        assert result["retrieval_result"][0]["title"] == "RAG"

    def test_truncates_web_search_result_content(self):
        output = {"web_search_result": [{"content": "y" * 300, "title": "t"}]}
        result = extract_trace_output("web_search", output)
        assert len(result["web_search_result"][0]["content"]) == 201

    def test_truncates_reasoning_steps_strings(self):
        output = {
            "needs_decomposition": True,
            "reasoning_steps": ["z" * 300, "短问题"],
        }
        result = extract_trace_output("decompose_question", output)
        assert len(result["reasoning_steps"][0]) == 201
        assert result["reasoning_steps"][1] == "短问题"

    def test_judge_log_takes_last_entry_only(self):
        # judge_log 是 add reducer 累积的，只下发当前节点的最后一条
        output = {
            "rag_quality_pass": False,
            "judge_log": [
                {"judge_type": "is_relevant", "passed": True},
                {
                    "judge_type": "is_retrieval_quality",
                    "passed": False,
                    "raw_output": {"reason": "low reranker score"},
                },
            ],
        }
        result = extract_trace_output("rag_quality_eval", output)
        assert result["rag_quality_pass"] is False
        assert result["judge_log"]["judge_type"] == "is_retrieval_quality"

    def test_missing_whitelisted_field_skipped(self):
        # 节点异常退回路径只返回部分字段
        assert extract_trace_output("query_corrector", {"correction_count": 1}) == {
            "correction_count": 1
        }

    def test_combined_quality_check_fields(self):
        output = {
            "has_hallucination": False,
            "answer_quality_pass": True,
            "judge_log": [{"judge_type": "combined_quality", "passed": True}],
        }
        result = extract_trace_output("combined_quality_check", output)
        assert set(result.keys()) == {
            "has_hallucination",
            "answer_quality_pass",
            "judge_log",
        }


class TestExtractReasoningContent:
    def test_from_object_additional_kwargs(self):
        class FakeChunk:
            additional_kwargs = {"reasoning_content": "思考中"}

        assert extract_reasoning_content(FakeChunk()) == "思考中"

    def test_from_object_empty_kwargs(self):
        class FakeChunk:
            additional_kwargs = {}

        assert extract_reasoning_content(FakeChunk()) == ""

    def test_from_dict_additional_kwargs(self):
        chunk = {"content": "答", "additional_kwargs": {"reasoning_content": "思"}}
        assert extract_reasoning_content(chunk) == "思"

    def test_from_dict_top_level_fallback(self):
        chunk = {"content": "答", "reasoning_content": "思"}
        assert extract_reasoning_content(chunk) == "思"

    def test_missing_returns_empty(self):
        assert extract_reasoning_content({"content": "x"}) == ""
        assert extract_reasoning_content("not-a-chunk") == ""
        assert extract_reasoning_content(None) == ""

    def test_object_without_kwargs_attr(self):
        class FakeChunk:
            content = "x"

        assert extract_reasoning_content(FakeChunk()) == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `cd backend && python -m pytest tests/unit/test_trace.py -q`（或仓库根 `python -m pytest backend/tests/unit/test_trace.py -q`）
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.trace'`

- [ ] **Step 3: 实现 trace.py**

创建 `backend/app/api/trace.py`：

```python
# backend/app/api/trace.py
"""思考过程可视化的 trace 工具：节点中文标签、output 白名单提取、reasoning 捞取。

设计依据：docs/superpowers/specs/2026-08-16-trace-visualization-design.md
- 白名单外的 state 字段一律不下发（控制 payload、避免泄露内部 state）
- 长文本截断 200 字符
- judge_log 是 add reducer 累积的，节点粒度只下发最后一条
"""

STAGE_LABELS = {
    "rewrite_query": "正在理解问题...",
    "decompose_question": "正在分析问题类型...",
    "chitchat_node": "正在回应...",
    "judge_relevance": "正在判断问题类型...",
    "rag_retrieve": "正在检索知识库...",
    "rag_quality_eval": "正在评估检索质量...",
    "query_corrector": "正在优化检索词...",
    "web_search": "正在联网搜索...",
    "generate_local": "正在生成回答...",
    "generate_online": "正在生成回答...",
    "multi_step_reason": "正在逐步推理...",
    "combined_quality_check": "正在评估答案质量...",
    "quality_fail": "正在生成提示...",
}


def stage_label(node_name: str) -> str:
    """节点名 → 中文标签（白名单外节点兜底文案）。"""
    return STAGE_LABELS.get(node_name, f"执行: {node_name}")


# 每个节点下发哪些 output 字段（字段名与 graph/nodes.py 实际返回对齐）
TRACE_OUTPUT_FIELDS: dict[str, list[str]] = {
    "rewrite_query": ["rewritten_query"],
    "decompose_question": ["is_chitchat", "needs_decomposition", "reasoning_steps"],
    "judge_relevance": ["is_relevant", "judge_log"],
    "rag_retrieve": ["retrieval_result", "avg_reranker_score"],
    "rag_quality_eval": ["rag_quality_pass", "judge_log"],
    "query_corrector": ["rewritten_query", "correction_count"],
    "web_search": ["web_search_result"],
    "combined_quality_check": [
        "has_hallucination",
        "answer_quality_pass",
        "judge_log",
    ],
    "quality_fail": ["quality_warning"],
}
# chitchat_node / generate_local / generate_online / multi_step_reason
# 无白名单字段（正文走 token 流），仅显示名称+耗时。

_TRUNCATE_LIMIT = 200
_TRUNCATE_LIST_FIELDS = ("retrieval_result", "web_search_result", "reasoning_steps")


def truncate_text(text: str, limit: int = _TRUNCATE_LIMIT) -> str:
    """截断长文本，超限时末尾以省略号标记。非字符串原样返回。"""
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return text[:limit] + "…"


def _truncate_item(item: object) -> object:
    """截断列表内条目：dict 截 content 字段，str 直接截断。"""
    if isinstance(item, dict):
        clipped = dict(item)
        if isinstance(clipped.get("content"), str):
            clipped["content"] = truncate_text(clipped["content"])
        return clipped
    if isinstance(item, str):
        return truncate_text(item)
    return item


def extract_trace_output(node_name: str, output: dict | None) -> dict:
    """按白名单提取节点 output 的关键字段（构建 node_end 事件的 output）。

    - 白名单外的字段一律丢弃
    - judge_log 只取最后一条（当前节点的判断记录）
    - 列表字段（retrieval/web_search/reasoning_steps）内每条截断 200 字
    """
    if not output:
        return {}
    fields = TRACE_OUTPUT_FIELDS.get(node_name)
    if not fields:
        return {}
    result: dict = {}
    for f in fields:
        if f not in output:
            continue
        v = output[f]
        if f == "judge_log":
            if isinstance(v, list) and v:
                result[f] = v[-1]
        elif isinstance(v, list) and f in _TRUNCATE_LIST_FIELDS:
            result[f] = [_truncate_item(item) for item in v]
        else:
            result[f] = v
    return result


def extract_reasoning_content(chunk: object) -> str:
    """从流式 chunk 中提取 deepseek-reasoner 思维链增量，取不到返回空串。

    langchain-openai 把 reasoning_content 放在 additional_kwargs（AIMessageChunk）；
    兼容 dict 形态（含顶层 fallback）。调用方对空串跳过下发。
    """
    if hasattr(chunk, "additional_kwargs"):
        kwargs = chunk.additional_kwargs or {}
        return kwargs.get("reasoning_content") or ""
    if isinstance(chunk, dict):
        kwargs = chunk.get("additional_kwargs") or {}
        return (
            kwargs.get("reasoning_content")
            or chunk.get("reasoning_content")
            or ""
        )
    return ""
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest backend/tests/unit/test_trace.py -q`
Expected: PASS（全部用例）

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/trace.py backend/tests/unit/test_trace.py
git commit -m "feat(trace): 新增 trace 纯函数模块（节点标签/output 白名单/截断/reasoning 提取）"
```

---

### Task 2: 后端事件循环改造（stage 结构升级 + node_end + reasoning 事件）

**Files:**
- Modify: `backend/app/api/chat.py:54-68`（删除 STAGE_LABELS，改 import）、`chat.py:110-138`（事件循环）
- Test: `backend/tests/integration/test_api_chat.py`（新增 4 个用例）

- [ ] **Step 1: 写失败的集成测试**

在 `backend/tests/integration/test_api_chat.py` 末尾追加（保留现有用例不动）：

```python
# ---------- 思考过程可视化：stage 结构升级 + node_end + reasoning 事件 ----------

def _make_mock_graph(events: list[dict]):
    async def mock_stream(*args, **kwargs):
        for e in events:
            yield e

    return type("G", (), {"astream_events": mock_stream})()


async def _collect_sse_events(client, conv_id: str, mock_graph, monkeypatch) -> list[dict]:
    from app.api import chat as chat_module

    monkeypatch.setattr(chat_module, "get_graph", lambda: mock_graph)
    events = []
    async with client.stream(
        "POST", "/api/chat", json={"conversation_id": conv_id, "message": "你好"},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


@pytest.mark.asyncio
async def test_chat_stage_event_has_node_and_label(client, monkeypatch):
    """stage 事件 data 从裸 string 升级为 {node, label}；LangGraph 总节点不发 stage。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph([
        {"event": "on_chain_start", "name": "LangGraph", "data": {}},
        {"event": "on_chain_start", "name": "rewrite_query", "data": {}},
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "t", "route_path": "chitchat", "judge_log": []}},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    stages = [e for e in events if e["type"] == "stage"]
    assert len(stages) == 1  # LangGraph 本身不发 stage
    assert stages[0]["data"] == {"node": "rewrite_query", "label": "正在理解问题..."}


@pytest.mark.asyncio
async def test_chat_emits_node_end_with_whitelisted_output(client, monkeypatch):
    """node_end 事件：含 node/label/duration_ms/output，output 走白名单过滤。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph([
        {"event": "on_chain_start", "name": "rewrite_query", "data": {}},
        {
            "event": "on_chain_end",
            "name": "rewrite_query",
            "data": {"output": {"rewritten_query": "什么是 RAG", "route_path": "local"}},
        },
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "t", "route_path": "chitchat", "judge_log": []}},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    node_ends = [e for e in events if e["type"] == "node_end"]
    assert len(node_ends) == 1  # LangGraph 的 on_chain_end 不产生 node_end
    payload = node_ends[0]["data"]
    assert payload["node"] == "rewrite_query"
    assert payload["label"] == "正在理解问题..."
    assert isinstance(payload["duration_ms"], int)
    assert payload["duration_ms"] >= 0
    # route_path 不在白名单内，被过滤
    assert payload["output"] == {"rewritten_query": "什么是 RAG"}


@pytest.mark.asyncio
async def test_chat_emits_reasoning_from_chunk(client, monkeypatch):
    """chunk 含 reasoning_content 时下发 reasoning 事件（增量文本）。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph([
        {"event": "on_llm_stream", "data": {"chunk": {
            "content": "",
            "additional_kwargs": {"reasoning_content": "用户在问 RAG..."},
        }}},
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "t", "route_path": "chitchat", "judge_log": []}},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    reasonings = [e for e in events if e["type"] == "reasoning"]
    assert len(reasonings) == 1
    assert reasonings[0]["data"] == "用户在问 RAG..."


@pytest.mark.asyncio
async def test_chat_no_reasoning_when_chunk_lacks_field(client, monkeypatch):
    """普通模型 chunk 无 reasoning_content → 不发 reasoning 事件。"""
    create = await client.post("/api/conversations", json={})
    conv_id = create.json()["id"]

    graph = _make_mock_graph([
        {"event": "on_llm_stream", "data": {"chunk": {"content": "答"}}},
        {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": "t", "route_path": "chitchat", "judge_log": []}},
        },
    ])
    events = await _collect_sse_events(client, conv_id, graph, monkeypatch)

    assert "reasoning" not in [e["type"] for e in events]
    assert "token" in [e["type"] for e in events]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest backend/tests/integration/test_api_chat.py -q`
Expected: 新增 4 个用例 FAIL（stage data 仍是裸 string / 无 node_end / 无 reasoning）；原有 4 个用例 PASS

- [ ] **Step 3: 改造 chat.py 事件循环**

修改 `backend/app/api/chat.py`。共 3 处改动：

**改动 1** — 删除 `chat.py:54-68` 的 `STAGE_LABELS = {...}` 整块定义，替换为 import（放在文件顶部 import 区，`from app.extensions import limiter` 之后）：

```python
from app.api.trace import (
    extract_reasoning_content,
    extract_trace_output,
    stage_label,
)
```

**改动 2** — `event_generator` 内，在 `try:` 之后、`runnable_config` 定义之前加节点计时字典：

```python
    async def event_generator():
        final_state = None
        error_msg = None  # 异常时填充，finally 落库用
        node_start_times: dict[str, float] = {}  # 节点执行开始时间（计算 duration_ms）
        try:
```

**改动 3** — 将 `chat.py:110-137` 的整个 `async for event in ...` 循环体替换为：

```python
            async for event in graph.astream_events(
                input_state, version="v2", config=runnable_config
            ):
                if event["event"] == "on_chain_start":
                    node_name = event["name"]
                    if node_name == "LangGraph":
                        continue  # 总图入口不发 stage
                    node_start_times[node_name] = time.time()
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "stage",
                                "data": {
                                    "node": node_name,
                                    "label": stage_label(node_name),
                                },
                            }
                        ),
                    }
                elif event["event"] in ("on_chat_model_stream", "on_llm_stream"):
                    # on_chat_model_stream: ChatOpenAI 等 BaseChatModel 的流式事件
                    # on_llm_stream: BaseLLM（非 chat）的流式事件（兼容保留）
                    chunk = event["data"]["chunk"]
                    # chunk 可能是对象（含 .content 属性）或 dict（含 "content" 键）
                    if hasattr(chunk, "content"):
                        content = chunk.content
                    elif isinstance(chunk, dict):
                        content = chunk.get("content", "")
                    else:
                        content = ""
                    if content:
                        yield {
                            "event": "message",
                            "data": json.dumps({"type": "token", "data": content}),
                        }
                    # deepseek-reasoner 思维链增量（其余模型为空串，静默跳过）
                    reasoning = extract_reasoning_content(chunk)
                    if reasoning:
                        yield {
                            "event": "message",
                            "data": json.dumps(
                                {"type": "reasoning", "data": reasoning}
                            ),
                        }
                elif event["event"] == "on_chain_end":
                    if event["name"] == "LangGraph":
                        final_state = event["data"]["output"]
                        continue
                    node_name = event["name"]
                    duration_ms = int(
                        (time.time() - node_start_times.get(node_name, time.time()))
                        * 1000
                    )
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "node_end",
                                "data": {
                                    "node": node_name,
                                    "label": stage_label(node_name),
                                    "duration_ms": duration_ms,
                                    "output": extract_trace_output(
                                        node_name, event["data"].get("output")
                                    ),
                                },
                            }
                        ),
                    }
```

注意：CRAG 回路中同名节点二次执行时 `node_start_times[node_name]` 被新的 start 覆盖，与对应 end 按事件顺序配对，行为正确。

- [ ] **Step 4: 运行确认全部通过**

Run: `python -m pytest backend/tests/integration/test_api_chat.py backend/tests/unit/test_trace.py -q`
Expected: PASS（含原有用例——原 `test_chat_returns_sse_stream` 只断言 type 存在，兼容新结构）

- [ ] **Step 5: 跑全量后端测试防回归**

Run: `python -m pytest backend/tests -q`
Expected: 全部 PASS。若有因 `stage` mock 未带 `name` 的既有用例失败（`event["name"]` KeyError），在该 mock 事件 dict 里补 `"name": "rewrite_query"` 字段即可。

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/chat.py backend/tests/integration/test_api_chat.py
git commit -m "feat(trace): SSE 事件协议升级（stage 带 node/label + 新增 node_end/reasoning 事件）"
```

---

### Task 3: 前端类型定义与事件分发

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/chat.ts:98-126`
- Test: `frontend/src/api/__tests__/chat.test.ts`（更新 2 处 stage 断言 + 新增 2 用例）

- [ ] **Step 1: 更新类型定义**

在 `frontend/src/types/index.ts` 中：

(a) `Message` 接口（第 25-38 行）的运行时状态区追加 3 个字段：

```ts
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  route_path?: string
  sources?: Source[]
  judge_log?: JudgeResult[]
  quality_warning?: string  // P1-3: 质量不合格时的警告文本
  query_log_id?: string  // 第 2 阶段：绑定 query_log，供反馈接口使用
  created_at: string
  // 前端运行时状态（不持久化）
  isStreaming?: boolean
  currentStage?: string
  // 思考过程可视化（不持久化，仅实时流）
  trace?: TraceNode[]
  traceStartedAt?: number
  traceDurationMs?: number
}
```

(b) 文件末尾（`StreamCallbacks` 之前）追加 trace 相关类型：

```ts
// 思考过程可视化：trace 节点与 SSE payload
export type TraceNodeStatus = 'running' | 'done' | 'error'

export interface TraceNode {
  node: string
  label: string
  status: TraceNodeStatus
  durationMs?: number
  output?: Record<string, unknown>
  reasoning?: string
}

export interface StagePayload {
  node: string
  label: string
}

export interface NodeEndPayload {
  node: string
  label: string
  duration_ms: number
  output: Record<string, unknown>
}
```

(c) `StreamCallbacks`（文件末尾）改为（`onStage` 签名升级，新增两个**可选**回调）：

```ts
export interface StreamCallbacks {
  onStage: (stage: StagePayload) => void
  onToken: (token: string) => void
  onReasoning?: (text: string) => void
  onNodeEnd?: (payload: NodeEndPayload) => void
  onMeta: (meta: ChatMeta) => void
  onError: (message: string) => void
  onDone: () => void
}
```

- [ ] **Step 2: 写失败的测试（更新 chat.test.ts）**

在 `frontend/src/api/__tests__/chat.test.ts` 中：

(a) 第一个用例 `parses stage / token / done events`（第 16-45 行）整体替换为：

```ts
  it('parses stage / token / done events', async () => {
    const sseData = [
      'data: {"type":"stage","data":{"node":"rag_retrieve","label":"正在检索知识库..."}}',
      '',
      'data: {"type":"token","data":"你好"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    const events: Array<{ type: string; data?: unknown }> = []
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
      { type: 'stage', data: { node: 'rag_retrieve', label: '正在检索知识库...' } },
      { type: 'token', data: '你好' },
      { type: 'done' },
    ])
  })
```

(b) 用例 `parses CRLF line endings (sse-starlette format)`（第 163-197 行）中的 stage 行与断言替换：

```ts
    // 构造数据中的 stage 行改为：
    'data: {"type":"stage","data":{"node":"rag_retrieve","label":"正在检索知识库..."}}',
    // ...
    // 断言改为：
    expect(events).toEqual([
      { type: 'stage', data: { node: 'rag_retrieve', label: '正在检索知识库...' } },
      { type: 'token', data: '你好' },
      { type: 'done' },
    ])
```

(c) 文件末尾追加 2 个用例：

```ts
  it('dispatches node_end and reasoning events', async () => {
    const sseData = [
      'data: {"type":"node_end","data":{"node":"rewrite_query","label":"正在理解问题...","duration_ms":120,"output":{"rewritten_query":"什么是 RAG"}}}',
      '',
      'data: {"type":"reasoning","data":"用户在问 RAG"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    const nodeEnds: unknown[] = []
    const reasonings: string[] = []
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onNodeEnd: (p) => nodeEnds.push(p),
        onReasoning: (t) => reasonings.push(t),
        onMeta: () => {},
        onError: () => {},
        onDone: () => {},
      }
    )

    expect(nodeEnds).toEqual([
      {
        node: 'rewrite_query',
        label: '正在理解问题...',
        duration_ms: 120,
        output: { rewritten_query: '什么是 RAG' },
      },
    ])
    expect(reasonings).toEqual(['用户在问 RAG'])
  })

  it('tolerates missing optional onNodeEnd/onReasoning callbacks', async () => {
    const sseData = [
      'data: {"type":"node_end","data":{"node":"x","label":"y","duration_ms":1,"output":{}}}',
      '',
      'data: {"type":"reasoning","data":"z"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    let done = false
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onMeta: () => {},
        onError: () => {},
        onDone: () => { done = true },
      }
    )
    expect(done).toBe(true) // 可选回调缺失时不抛错
  })
```

- [ ] **Step 3: 运行确认失败**

Run: `cd frontend && npm run test`
Expected: FAIL（node_end/reasoning 不被分发；stage 断言仍是 string 时 `onStage` 收到 object）

- [ ] **Step 4: 实现 chat.ts 分发**

`frontend/src/api/chat.ts` 的 `dispatchEvent`（第 98-126 行）switch 增加两个分支、更新 stage 分支：

```ts
function dispatchEvent(rawData: string, cb: StreamCallbacks): void {
  let parsed: { type: string; data?: unknown }
  try {
    parsed = JSON.parse(rawData)
  } catch {
    return // 非 JSON（心跳或注释），忽略
  }
  switch (parsed.type) {
    case 'stage':
      cb.onStage(parsed.data as StagePayload)
      break
    case 'token':
      cb.onToken(parsed.data as string)
      break
    case 'reasoning':
      cb.onReasoning?.(parsed.data as string)
      break
    case 'node_end':
      cb.onNodeEnd?.(parsed.data as NodeEndPayload)
      break
    case 'meta':
      cb.onMeta(parsed.data as ChatMeta)
      break
    case 'error':
      cb.onError(
        (parsed.data && typeof parsed.data === 'object' && 'message' in parsed.data
          ? String((parsed.data as { message: unknown }).message)
          : '未知错误')
      )
      break
    case 'done':
      cb.onDone()
      break
  }
}
```

同时文件顶部 import 更新（第 4 行）：

```ts
import type { ChatRequest, StreamCallbacks, ChatMeta, StagePayload, NodeEndPayload } from '@/types'
```

- [ ] **Step 5: 运行确认通过**

Run: `cd frontend && npm run test`
Expected: `src/api/__tests__/chat.test.ts` 全部 PASS（store 测试可能因 mock 用旧 stage 结构失败，属 Task 4 范围，此时可临时跳过：`npx vitest run src/api`）

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/chat.ts frontend/src/api/__tests__/chat.test.ts
git commit -m "feat(trace): 前端类型与 SSE 分发支持 node_end/reasoning 事件"
```

---

### Task 4: store trace 状态机（事件 → TraceNode[]）

**Files:**
- Modify: `frontend/src/stores/chat.ts:174-281`（doSend 回调区）+ `stopStreaming`
- Test: `frontend/src/stores/__tests__/chat.test.ts`（更新 1 处 mock + 新增 3 用例）

- [ ] **Step 1: 写失败的测试**

在 `frontend/src/stores/__tests__/chat.test.ts` 中：

(a) 用例 `sendMessage creates conversation if none selected`（第 43-48 行）的 mock 更新为新 stage 结构：

```ts
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onStage({ node: 'rewrite_query', label: '正在理解问题...' })
      cb.onToken('回')
      cb.onToken('答')
      cb.onDone()
    })
```

(b) 文件末尾（`describe` 闭合前）追加 3 个用例：

```ts
  it('sendMessage maintains trace state machine with CRAG loop', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onStage({ node: 'rewrite_query', label: '正在理解问题...' })
      cb.onNodeEnd({ node: 'rewrite_query', label: '正在理解问题...', duration_ms: 120, output: { rewritten_query: '什么是 RAG' } })
      cb.onStage({ node: 'rag_retrieve', label: '正在检索知识库...' })
      cb.onNodeEnd({ node: 'rag_retrieve', label: '正在检索知识库...', duration_ms: 300, output: { avg_reranker_score: 0.2 } })
      // CRAG 回路：同名节点第二次执行，追加第二个节点行
      cb.onStage({ node: 'rag_retrieve', label: '正在检索知识库...' })
      cb.onNodeEnd({ node: 'rag_retrieve', label: '正在检索知识库...', duration_ms: 350, output: { avg_reranker_score: 0.8 } })
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    const trace = store.messages[1].trace!
    expect(trace.length).toBe(3)
    expect(trace[0]).toMatchObject({
      node: 'rewrite_query', status: 'done', durationMs: 120,
      output: { rewritten_query: '什么是 RAG' },
    })
    expect(trace[1]).toMatchObject({ node: 'rag_retrieve', status: 'done', durationMs: 300 })
    expect(trace[2]).toMatchObject({ node: 'rag_retrieve', status: 'done', durationMs: 350 })
    // 挂钟总时长已记录
    expect(typeof store.messages[1].traceDurationMs).toBe('number')
  })

  it('reasoning accumulates on the current running node', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onStage({ node: 'multi_step_reason', label: '正在逐步推理...' })
      cb.onReasoning?.('第一步，')
      cb.onReasoning?.('分析问题。')
      cb.onNodeEnd({ node: 'multi_step_reason', label: '正在逐步推理...', duration_ms: 900, output: {} })
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    const trace = store.messages[1].trace!
    expect(trace[0].reasoning).toBe('第一步，分析问题。')
    expect(trace[0].status).toBe('done')
  })

  it('error event marks running trace node as error', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onStage({ node: 'rewrite_query', label: '正在理解问题...' })
      cb.onStage({ node: 'rag_retrieve', label: '正在检索知识库...' })
      cb.onError('LLM 调用失败')
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    const trace = store.messages[1].trace!
    // onError 后 running 节点标 error；已 done 的不受影响
    expect(trace[0].status).toBe('error')  // 注意：mock 中 rewrite_query 未发 node_end
    expect(trace[1].status).toBe('error')
  })
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/stores`
Expected: 新增 3 用例 FAIL（`trace` 为 undefined）；更新过的旧用例 FAIL（`currentStage` 变 undefined）

- [ ] **Step 3: 实现 store 状态机**

修改 `frontend/src/stores/chat.ts`：

(a) `stopStreaming`（第 107-121 行）在 `m.currentStage = ''` 之后加一行（手动停止把 running 节点置 done，避免 spinner 悬挂）：

```ts
  function stopStreaming(): void {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    // 重置当前助手消息的流式状态
    const m = messages.value[messages.value.length - 1]
    if (m && m.role === 'assistant' && m.isStreaming) {
      m.isStreaming = false
      m.currentStage = ''
      finalizeRunningTrace(m, 'done')
      // 如果用户主动停止且已有内容，保留内容；无内容则标记为已停止
      if (!m.content) m.content = '_(已停止)_'
    }
    isStreaming.value = false
  }
```

(b) `doSend` 内 `assistantMsg`（第 190-197 行）初始化加 `trace: []`：

```ts
    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      isStreaming: true,
      currentStage: '',
      trace: [],
    }
```

(c) 在 `doSend` 之前（`editUserMessage` 之后）加两个辅助函数：

```ts
  /** 取最后一条 assistant 消息（流式回调的目标）。 */
  function lastAssistant(): Message | null {
    const m = messages.value[messages.value.length - 1]
    return m && m.role === 'assistant' ? m : null
  }

  /** 把 trace 中所有 running 节点置为指定状态（error=后端异常，done=正常/手动停止收尾）。 */
  function finalizeRunningTrace(m: Message | null, status: 'done' | 'error'): void {
    if (!m?.trace) return
    for (const t of m.trace) {
      if (t.status === 'running') t.status = status
    }
  }
```

(d) `streamChat` 回调区（第 209-244 行）整体替换为：

```ts
        {
          onStage: (stage) => {
            const m = lastAssistant()
            if (!m) return
            m.currentStage = stage.label  // 保留：MessageList 滚动 watch 依赖
            if (!m.trace) m.trace = []
            if (!m.traceStartedAt) m.traceStartedAt = Date.now()
            m.trace.push({ node: stage.node, label: stage.label, status: 'running' })
          },
          onReasoning: (text) => {
            const m = lastAssistant()
            if (!m?.trace) return
            // 累加到最近的 running 节点（reasoning 发生在生成节点执行期间）
            for (let i = m.trace.length - 1; i >= 0; i--) {
              if (m.trace[i].status === 'running') {
                m.trace[i].reasoning = (m.trace[i].reasoning || '') + text
                break
              }
            }
          },
          onNodeEnd: (payload) => {
            const m = lastAssistant()
            if (!m?.trace) return
            // 从后往前配对同名 running 节点（CRAG 回路多次执行各自配对）
            for (let i = m.trace.length - 1; i >= 0; i--) {
              if (m.trace[i].node === payload.node && m.trace[i].status === 'running') {
                m.trace[i].status = 'done'
                m.trace[i].durationMs = payload.duration_ms
                m.trace[i].output = payload.output
                break
              }
            }
          },
          onToken: (token) => {
            const m = lastAssistant()
            if (m) m.content += token
          },
          onMeta: (meta: ChatMeta) => {
            const m = lastAssistant()
            if (m) {
              m.route_path = meta.route_path
              m.sources = meta.sources
              m.judge_log = meta.judge_log
              // P1-3: 接收质量警告（仅 quality_fail 路径有值）
              if (meta.quality_warning) m.quality_warning = meta.quality_warning
              // 第 2 阶段：绑定 query_log_id，供反馈接口使用
              if (meta.query_log_id) m.query_log_id = meta.query_log_id
            }
          },
          onError: (msg) => {
            error.value = msg
            const m = lastAssistant()
            if (m) {
              m.isStreaming = false
              finalizeRunningTrace(m, 'error')
              if (!m.content) m.content = `**错误**：${msg}`
            }
          },
          onDone: () => {
            const m = lastAssistant()
            if (m) {
              m.isStreaming = false
              m.currentStage = ''
              finalizeRunningTrace(m, 'done')
              if (m.traceStartedAt !== undefined) {
                m.traceDurationMs = Date.now() - m.traceStartedAt
              }
            }
            isStreaming.value = false
          },
        },
```

(e) catch 分支的 AbortError 处理（第 250-259 行）加 finalize（保持原有逻辑，插入一行）：

```ts
      if (e instanceof Error && e.name === 'AbortError') {
        const m = messages.value[messages.value.length - 1]
        if (m && m.role === 'assistant' && m.isStreaming) {
          m.isStreaming = false
          m.currentStage = ''
          finalizeRunningTrace(m, 'done')
          if (!m.content) m.content = '_(已停止)_'
        }
        isStreaming.value = false
        return
      }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd frontend && npm run test`
Expected: `src/stores` 与 `src/api` 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/chat.ts frontend/src/stores/__tests__/chat.test.ts
git commit -m "feat(trace): store 维护 trace 状态机（running/done/error + reasoning 累加 + CRAG 双节点配对）"
```

---

### Task 5: TraceTimeline 组件 + 集成 + 删除 StageIndicator

**Files:**
- Create: `frontend/src/components/TraceTimeline.vue`
- Modify: `frontend/src/components/AssistantMessage.vue:8,88`
- Delete: `frontend/src/components/StageIndicator.vue`

- [ ] **Step 1: 创建 TraceTimeline.vue**

```vue
<!-- frontend/src/components/TraceTimeline.vue -->
<!-- 思考过程可视化：流式期间垂直 timeline 逐节点点亮；完成后折叠为"已深度思考"摘要行。
     设计依据：docs/superpowers/specs/2026-08-16-trace-visualization-design.md -->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { TraceNode } from '@/types'
import { Loader2, Check, X, ChevronRight } from 'lucide-vue-next'

const props = defineProps<{
  trace: TraceNode[]
  streaming: boolean
  durationMs?: number
}>()

// 完成后默认折叠；重新进入流式时自动展开
const collapsed = ref(false)
watch(
  () => props.streaming,
  (v) => { collapsed.value = !v },
  { immediate: true }
)

// 各节点行的展开状态（下标为 key，CRAG 回路同名节点独立展开）
const expandedRows = ref<Set<number>>(new Set())
function toggleRow(i: number): void {
  if (expandedRows.value.has(i)) expandedRows.value.delete(i)
  else expandedRows.value.add(i)
}
function hasDetail(n: TraceNode): boolean {
  return Boolean(n.reasoning || (n.output && Object.keys(n.output).length > 0))
}

// reasoning 展开区自动滚动到底（思维流实时 append）
const reasoningEls = ref<Record<number, HTMLElement | null>>({})
watch(
  () => props.trace.map((t) => t.reasoning?.length ?? 0).join(','),
  async () => {
    await nextTick()
    for (const el of Object.values(reasoningEls.value)) {
      if (el) el.scrollTop = el.scrollHeight
    }
  }
)

function formatMs(ms?: number): string {
  if (ms === undefined) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

// output 字段的中文标签（与后端 TRACE_OUTPUT_FIELDS 白名单字段对齐）
const FIELD_LABELS: Record<string, string> = {
  rewritten_query: '改写后的问题',
  is_chitchat: '闲聊问题',
  needs_decomposition: '需要分解',
  reasoning_steps: '子问题',
  is_relevant: '知识库相关',
  retrieval_result: '检索到的文档',
  avg_reranker_score: '重排均分',
  rag_quality_pass: '检索质量通过',
  correction_count: '纠正次数',
  web_search_result: '联网搜索结果',
  has_hallucination: '疑似幻觉',
  answer_quality_pass: '答案质量通过',
  quality_warning: '质量警告',
  judge_log: '判断依据',
}

interface OutputRow {
  label: string
  text?: string
  bool?: boolean
  number?: number
  docs?: { title: string; score?: number; content: string }[]
  steps?: string[]
}

function outputRows(n: TraceNode): OutputRow[] {
  const rows: OutputRow[] = []
  for (const [key, value] of Object.entries(n.output ?? {})) {
    const label = FIELD_LABELS[key] ?? key
    if (key === 'retrieval_result' || key === 'web_search_result') {
      rows.push({
        label,
        docs: (value as Array<Record<string, unknown>>).map((d) => ({
          title: String(d.title ?? d.source ?? '未知来源'),
          score: typeof d.score === 'number' ? d.score : undefined,
          content: String(d.content ?? ''),
        })),
      })
    } else if (key === 'reasoning_steps') {
      rows.push({ label, steps: (value as unknown[]).map(String) })
    } else if (typeof value === 'boolean') {
      rows.push({ label, bool: value })
    } else if (key === 'judge_log') {
      const j = value as { raw_output?: { reason?: string }; judge_type?: string }
      rows.push({ label, text: j?.raw_output?.reason ?? j?.judge_type ?? '' })
    } else if (typeof value === 'number') {
      rows.push({ label, number: value })
    } else {
      rows.push({ label, text: String(value) })
    }
  }
  return rows
}
</script>

<template>
  <div class="text-sm py-1">
    <!-- 折叠态摘要行（完成后） -->
    <button
      v-if="collapsed"
      @click="collapsed = false"
      class="flex items-center gap-1.5 text-xs text-gray-500 hover:text-stone-700 transition-colors"
    >
      <span class="w-4 h-4 rounded-full bg-stone-100 flex items-center justify-center">
        <ChevronRight class="w-3 h-3" />
      </span>
      已深度思考<template v-if="durationMs !== undefined">（用时 {{ (durationMs / 1000).toFixed(1) }}s · {{ trace.length }} 个节点）</template>
    </button>

    <!-- 展开态 timeline -->
    <div v-else class="space-y-0.5">
      <button
        v-if="!streaming"
        @click="collapsed = true"
        class="text-xs text-gray-400 hover:text-stone-700 transition-colors"
      >
        收起思考过程
      </button>
      <TransitionGroup name="trace" tag="div" class="space-y-0.5">
        <div v-for="(node, i) in trace" :key="`${node.node}-${i}`">
          <!-- 节点行 -->
          <button
            @click="hasDetail(node) && toggleRow(i)"
            class="flex items-center gap-2 w-full text-left px-1 py-0.5 rounded hover:bg-gray-50 transition-colors"
            :class="hasDetail(node) ? 'cursor-pointer' : 'cursor-default'"
          >
            <span class="w-4 h-4 shrink-0 flex items-center justify-center">
              <Loader2 v-if="node.status === 'running'" class="w-3 h-3 animate-spin text-amber-500" />
              <Check v-else-if="node.status === 'done'" class="w-3 h-3 text-green-600" />
              <X v-else class="w-3 h-3 text-red-500" />
            </span>
            <span class="text-xs" :class="node.status === 'running' ? 'text-stone-700 font-medium' : 'text-gray-500'">
              {{ node.label }}
            </span>
            <span v-if="node.durationMs !== undefined" class="text-[10px] text-gray-400">
              {{ formatMs(node.durationMs) }}
            </span>
            <ChevronRight
              v-if="hasDetail(node)"
              class="w-3 h-3 text-gray-400 transition-transform"
              :class="expandedRows.has(i) ? 'rotate-90' : ''"
            />
          </button>

          <!-- 展开区：reasoning 思维流 + output 中间结果 -->
          <div v-if="expandedRows.has(i)" class="ml-6 mt-0.5 border-l-2 border-gray-100 pl-3 space-y-2 pb-1">
            <div
              v-if="node.reasoning"
              :ref="(el) => (reasoningEls[i] = el as HTMLElement | null)"
              class="max-h-48 overflow-y-auto text-xs text-gray-500 font-mono leading-relaxed whitespace-pre-wrap bg-gray-50 rounded-md p-2"
            >
              {{ node.reasoning }}
            </div>
            <div v-for="row in outputRows(node)" :key="row.label" class="text-xs text-gray-600">
              <span class="text-gray-400">{{ row.label }}：</span>
              <span v-if="row.bool !== undefined" :class="row.bool ? 'text-green-600' : 'text-red-500'">
                {{ row.bool ? '是' : '否' }}
              </span>
              <span v-else-if="row.number !== undefined" class="tabular-nums">{{ row.number.toFixed(4) }}</span>
              <span v-else-if="row.text">{{ row.text }}</span>
              <ol v-else-if="row.steps" class="list-decimal ml-4 space-y-0.5">
                <li v-for="(s, j) in row.steps" :key="j">{{ s }}</li>
              </ol>
              <div v-else-if="row.docs" class="space-y-1 mt-1">
                <div v-for="(d, j) in row.docs" :key="j" class="bg-gray-50 rounded-md p-1.5">
                  <div class="flex items-center justify-between gap-2">
                    <span class="font-medium text-gray-700 truncate">{{ d.title }}</span>
                    <span v-if="d.score !== undefined" class="text-[10px] text-gray-400 shrink-0">
                      {{ d.score.toFixed(3) }}
                    </span>
                  </div>
                  <p class="text-gray-500 line-clamp-3">{{ d.content }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
/* 节点行进入动画（Tailwind transition 不覆盖列表项） */
.trace-enter-active {
  transition: all 0.3s ease;
}
.trace-enter-from {
  opacity: 0;
  transform: translateX(-8px);
}
</style>
```

- [ ] **Step 2: AssistantMessage 集成 + 删除旧组件**

(a) `frontend/src/components/AssistantMessage.vue` 第 8 行 import 替换：

```ts
import TraceTimeline from './TraceTimeline.vue'
```

(b) 第 87-88 行 StageIndicator 调用替换为：

```vue
      <!-- 思考过程可视化：流式期间实时展开，完成后折叠（历史消息无 trace 不渲染） -->
      <TraceTimeline
        v-if="message.trace && message.trace.length"
        :trace="message.trace"
        :streaming="!!message.isStreaming"
        :duration-ms="message.traceDurationMs"
      />
```

(c) 删除文件 `frontend/src/components/StageIndicator.vue`（用工具删除，不要 git rm 留档）。

- [ ] **Step 3: 类型检查 + 全量测试**

Run: `cd frontend && npm run test && npx vue-tsc -b --noEmit 2>&1 | head -20`
Expected: vitest 全部 PASS；vue-tsc 无新增类型错误（`line-clamp-3` 需要 Tailwind 3.3+ 内置支持，无需配置）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/TraceTimeline.vue frontend/src/components/AssistantMessage.vue
git rm frontend/src/components/StageIndicator.vue
git commit -m "feat(trace): TraceTimeline 组件替代 StageIndicator（折叠摘要/节点展开/思维流滚动）"
```

---

### Task 6: 全量验证与手动验收

**Files:** 无新增（验证任务）

- [ ] **Step 1: 后端全量测试**

Run: `python -m pytest backend/tests -q`
Expected: 全部 PASS

- [ ] **Step 2: 前端全量测试 + 构建**

Run: `cd frontend && npm run test && npm run build`
Expected: 全部 PASS；`vue-tsc -b && vite build` 成功

- [ ] **Step 3: 手动验收（5 条路径，需启动前后端）**

启动后端 `uvicorn app.main:app --reload`（backend 目录）与前端 `npm run dev`，逐条验证：

1. **闲聊路径**（"你好"）：trace 显示 rewrite_query → decompose_question → chitchat_node，chitchat 节点无展开内容（无白名单字段），done 后折叠。
2. **本地 RAG 路径**（"什么是 RAG"）：judge_relevance 展开显示 `知识库相关: 是` + 判断依据；rag_retrieve 展开显示文档列表（title/分数/截断内容）；combined_quality_check 显示双布尔结论。
3. **CRAG 回路**（构造一个首次检索低分的问题，如生僻组合词）：出现两个 `正在检索知识库...` 节点行 + query_corrector 节点行，各自独立展开。
4. **分解路径**（"比较一下 RAG 和微调的区别，并说明各自适用场景"）：multi_step_reason 节点展开显示灰色思维流（reasoning_content），实时滚动；decompose_question 展开显示子问题编号列表。
5. **中断/错误**：流式期间点停止 → running 节点变 done、timeline 折叠；重启后端制造错误 → 当前节点标红。

- [ ] **Step 4: 验收通过后 Commit（如有微调）**

```bash
git add -A
git commit -m "fix(trace): 手动验收微调"
```

（无改动则跳过本步）

---

## Self-Review 记录

- **Spec 覆盖**：7 种 SSE 事件（Task 2/3）、output 白名单 13 节点（Task 1 `TRACE_OUTPUT_FIELDS`）、耗时统计（Task 2 挂钟差值）、reasoning 降级（Task 1 空串跳过）、TraceTimeline 三态（Task 5）、CRAG 双节点行（Task 4 配对逻辑 + 测试）、历史消息不渲染（Task 5 `v-if` guard）、错误标红（Task 4 finalize + Task 5 X 图标）——全部有对应任务。
- **类型一致性**：`TraceNode{node,label,status,durationMs,output,reasoning}` / `StagePayload{node,label}` / `NodeEndPayload{node,label,duration_ms,output}` / `Message.trace|traceStartedAt|traceDurationMs`，store 做 `duration_ms → durationMs` 映射，组件 props 与 types 一致。
- **占位符扫描**：无 TBD/TODO；所有代码步骤含完整代码。
- **已知风险**：`reasoning_content` 在 langchain-openai 真实 chunk 上的字段位置以 `additional_kwargs` 为主（Task 1 已做顶层 fallback），若实测字段异常，只需改 `extract_reasoning_content` 一处，不影响其他层。
