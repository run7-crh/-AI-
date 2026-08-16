# 知识图谱可视化（Knowledge Graph）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 离线构建 AI 概念知识图谱（规则+LLM 混合抽取 → kg.json），新增 `GET /api/graph` 与前端 `/graph` 力导向图页面，点击概念可一键发起 RAG 提问。

**Architecture:** 后端新增 `app/rag/graph_builder.py`（纯函数层：解析/归一化/对齐/规则边/合并，与 LLM 层分离可离线单测），构建挂在现有 `POST /api/index/rebuild` 成功后执行且失败不阻塞；前端新增 `GraphView.vue`（ECharts 按需引入力导向图）+ 侧边概念卡片 + 经 `?ask=` query 跳转聊天自动发问，与思考过程可视化形成闭环。

**Tech Stack:** 后端零新增（frontmatter/pydantic/现有 call_llm）；前端新增 `echarts@5`（唯一新增依赖）。

**Spec:** `docs/superpowers/specs/2026-08-16-knowledge-graph-design.md`（已评审通过）

**关键现状（实测确认，避免踩坑）：**
- raw 目录 20 个 md 中：`Agent智能体.md` 是 **37 字节损坏文件**（frontmatter 未闭合无正文）→ 靠"正文 < 200 字跳过"过滤；`RAG检索增强生成.md`（1883B 旧版）与 `RAG 检索增强生成.md`（21KB）**title 相同** → 同名去重取内容更长者。实际入库概念 18 个。
- `Agent.md` 的 title 是 `AI Agent 智能体`（非 "Agent 智能体"），aliases 含 `智能体`/`AI代理`。
- 19 个文件有 `## 十、相关知识` 章节，条目格式 `- [[LLM 大语言模型]] — 描述文字`；部分 wikilink 目标（如 `[[LangChain 入门]]`、`[[Multi-Agent 多智能体系统]]`）不在概念清单内 → 按规则丢弃该边。
- `call_llm`（`app/graph/tools.py:120`）带 tenacity 3 次重试，`output_schema` 走 function_calling，返回 `{"text": "", "structured": {...}}`。
- `readers.py` 的 wikilink 剥离**不动**——graph_builder 独立扫 raw 目录。
- 前端 dev 代理已配 `/api`（chat.ts 用相对路径 fetch）。
- 测试命令：后端 `& backend\.venv\Scripts\python.exe -m pytest backend/tests -q`（仓库根）；前端 `cd frontend && npm run test`。
- **执行模式（用户要求）**：所有任务先完成代码与测试代码编写，**跳过所有"运行测试"步骤**，统一测试在最后执行。提交照常进行。

---

### Task 1: graph_builder 纯函数层（解析/归一化/对齐/规则边/合并）

**Files:**
- Create: `backend/app/rag/graph_builder.py`
- Modify: `backend/app/config.py`（加 KG_JSON_PATH）
- Create: `backend/tests/unit/test_graph_builder.py`

- [ ] **Step 1: config.py 加产物路径**

在 `backend/app/config.py` 的 `SQLITE_PATH` 行之后加：

```python
    # 知识图谱产物（graph_builder 全量重建生成，GET /api/graph 直接读此文件）
    KG_JSON_PATH: str = str(_PROJECT_ROOT / "backend" / "data" / "kg.json")
```

- [ ] **Step 2: 写失败的单测**

创建 `backend/tests/unit/test_graph_builder.py`：

```python
# backend/tests/unit/test_graph_builder.py
"""graph_builder 纯函数层单测：解析/归一化/对齐/规则边/合并/度数。"""
import json

import pytest

from app.rag.graph_builder import (
    MIN_BODY_CHARS,
    align_concepts,
    build_rule_edges,
    compute_degrees,
    extract_related_section,
    extract_wikilinks,
    merge_edges,
    normalize_concept,
    parse_doc,
)


def _write_md(tmp_path, name, title=None, aliases=None, tags=None, body="正文" * 150):
    """生成测试用 Obsidian md（frontmatter + 正文）。"""
    fm = ["---"]
    if title:
        fm.append(f"title: {title}")
    if tags:
        fm.append("tags: [AI, 测试]")
    if aliases:
        fm.append("aliases:")
        fm.extend([f"  - {a}" for a in aliases])
    fm.append("---")
    content = "\n".join(fm) + "\n\n" + body
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestNormalizeConcept:
    def test_lowercase_and_strip_whitespace(self):
        assert normalize_concept("RAG 检索增强生成") == "rag检索增强生成"
        assert normalize_concept("  Agent 智能体 ") == "agent智能体"

    def test_mixed_case_with_underscore(self):
        assert normalize_concept("LangChain-LangGraph") == "langchain-langgraph"


class TestParseDoc:
    def test_parses_frontmatter(self, tmp_path):
        p = _write_md(
            tmp_path, "Agent.md", title="AI Agent 智能体",
            aliases=["智能体"], body="Agent 是..." * 100,
        )
        d = parse_doc(p)
        assert d is not None
        assert d.title == "AI Agent 智能体"
        assert d.aliases == ["智能体"]
        assert d.file == "Agent.md"

    def test_corrupted_short_file_skipped(self, tmp_path):
        # 复现 raw 目录的 37 字节损坏文件（frontmatter 未闭合）
        p = tmp_path / "Agent智能体.md"
        p.write_text("---\ntitle: Agent 智能体\ntags: [AI,", encoding="utf-8")
        assert parse_doc(p) is None

    def test_body_below_threshold_skipped(self, tmp_path):
        p = _write_md(tmp_path, "短文.md", title="短文", body="太短")
        assert parse_doc(p) is None
        assert MIN_BODY_CHARS == 200

    def test_title_falls_back_to_stem(self, tmp_path):
        p = _write_md(tmp_path, "无标题.md", body="有足够长的正文内容。" * 50)
        d = parse_doc(p)
        assert d is not None
        assert d.title == "无标题"

    def test_tags_string_form_flattened(self, tmp_path):
        p = _write_md(tmp_path, "行内标签.md", title="行内标签", body="正文" * 150)
        # _write_md 固定写 tags: [AI, 测试]，验证 list 形态
        d = parse_doc(p)
        assert d.tags == ["AI", "测试"]


class TestAlignConcepts:
    def test_duplicate_title_keeps_longer_content(self, tmp_path):
        old = _write_md(tmp_path, "RAG旧.md", title="RAG 检索增强生成", body="旧版短内容" * 50)
        new = _write_md(tmp_path, "RAG新.md", title="RAG 检索增强生成", body="新版完整内容" * 500)
        by_key, alias_to_id = align_concepts([parse_doc(old), parse_doc(new)])
        assert len(by_key) == 1
        cid = normalize_concept("RAG 检索增强生成")
        assert by_key[cid].file == "RAG新.md"  # 保留内容更长者

    def test_aliases_and_stem_registered(self, tmp_path):
        p = _write_md(
            tmp_path, "Agent.md", title="AI Agent 智能体",
            aliases=["智能体", "AI代理"], body="正文" * 200,
        )
        by_key, alias_to_id = align_concepts([parse_doc(p)])
        cid = normalize_concept("AI Agent 智能体")
        assert cid in by_key
        assert alias_to_id["智能体"] == cid
        assert alias_to_id["ai代理"] == cid
        assert alias_to_id["agent"] == cid  # stem 归一化

    def test_concept_id_is_normalized_title(self, tmp_path):
        p = _write_md(tmp_path, "RAG 检索增强生成.md", title="RAG 检索增强生成", body="正文" * 150)
        by_key, _ = align_concepts([parse_doc(p)])
        assert list(by_key.keys()) == ["rag检索增强生成"]


class TestExtractors:
    def test_wikilink_plain_and_alias(self):
        text = "参见 [[RAG 检索增强生成]] 与 [[Tool Calling 工具调用|工具调用]]"
        assert extract_wikilinks(text) == [
            "RAG 检索增强生成", "Tool Calling 工具调用",
        ]

    def test_related_section_items_with_description(self):
        text = (
            "## 九、小结\n内容\n\n## 十、相关知识\n\n"
            "- [[LLM 大语言模型]] — Agent 的\"大脑\"基础\n"
            "- [[RAG 检索增强生成]] — 外挂知识库\n\n"
            "## 十一、代码示例\n```python\npass\n```\n"
        )
        items = extract_related_section(text)
        assert items == [
            ("LLM 大语言模型", "Agent 的\"大脑\"基础"),
            ("RAG 检索增强生成", "外挂知识库"),
        ]

    def test_related_section_missing_returns_empty(self):
        assert extract_related_section("## 一、定义\n没有相关知识章节") == []


class TestBuildRuleEdges:
    def _two_concepts(self, tmp_path):
        """A（含指向 B 的 wikilink）+ B 两个概念。"""
        pa = _write_md(
            tmp_path, "Agent.md", title="AI Agent 智能体", aliases=["智能体"],
            body="Agent 依赖 [[RAG 检索增强生成]] 技术与 [[不存在的概念]]。\n\n"
                 "## 十、相关知识\n- [[RAG 检索增强生成]] — 外挂知识库\n",
        )
        pb = _write_md(tmp_path, "RAG.md", title="RAG 检索增强生成", body="RAG 是..." * 100)
        docs = [parse_doc(pa), parse_doc(pb)]
        by_key, alias_to_id = align_concepts(docs)
        return by_key, alias_to_id

    def test_edges_dedupe_and_unknown_target_dropped(self, tmp_path):
        by_key, alias_to_id = self._two_concepts(tmp_path)
        edges = build_rule_edges(by_key, alias_to_id)
        # wikilink 与相关知识章节指向同一目标 → 去重为一条；未知概念被丢弃
        assert len(edges) == 1
        e = edges[0]
        assert e["source"] == "aiagent智能体"
        assert e["target"] == "rag检索增强生成"
        assert e["type"] == "相关"
        assert e["via"] == "rule"
        # 相关知识章节的描述被保留（优先于无描述的正文 wikilink）
        assert e["description"] == "外挂知识库"

    def test_self_loop_dropped(self, tmp_path):
        pa = _write_md(
            tmp_path, "自指.md", title="自指概念",
            body="参见 [[自指概念]] 自身。" * 10,
        )
        by_key, alias_to_id = align_concepts([parse_doc(pa)])
        assert build_rule_edges(by_key, alias_to_id) == []


class TestMergeEdges:
    def test_llm_type_overrides_rule_via_stays_rule(self):
        rule = [{"source": "a", "target": "b", "type": "相关", "via": "rule", "description": "规则描述"}]
        llm = [{"source": "b", "target": "a", "type": "依赖", "via": "llm", "description": "LLM 描述"}]
        merged = merge_edges(rule, llm)
        assert len(merged) == 1
        assert merged[0]["type"] == "依赖"      # LLM 细分标注优先
        assert merged[0]["via"] == "rule"        # 规则覆盖过的对保持 rule
        assert merged[0]["description"] == "LLM 描述"

    def test_llm_only_edge_kept(self):
        llm = [{"source": "a", "target": "c", "type": "演进", "via": "llm", "description": ""}]
        merged = merge_edges([], llm)
        assert merged == [{"source": "a", "target": "c", "type": "演进", "via": "llm", "description": ""}]

    def test_undirected_pair_dedupe(self):
        rule = [{"source": "a", "target": "b", "type": "相关", "via": "rule", "description": ""}]
        llm = [
            {"source": "a", "target": "b", "type": "组成", "via": "llm", "description": ""},
            {"source": "b", "target": "a", "type": "依赖", "via": "llm", "description": ""},
        ]
        merged = merge_edges(rule, llm)
        assert len(merged) == 1  # (a,b) 无序对只留一条


class TestComputeDegrees:
    def test_degree_counts_merged_edges(self):
        nodes = [
            {"id": "a", "title": "A", "degree": 0},
            {"id": "b", "title": "B", "degree": 0},
            {"id": "c", "title": "C", "degree": 0},
        ]
        edges = [
            {"source": "a", "target": "b", "type": "相关", "via": "rule", "description": ""},
            {"source": "a", "target": "c", "type": "相关", "via": "rule", "description": ""},
        ]
        compute_degrees(nodes, edges)
        assert {n["id"]: n["degree"] for n in nodes} == {"a": 2, "b": 1, "c": 1}
```

- [ ] **Step 3: 实现纯函数层**

创建 `backend/app/rag/graph_builder.py`：

```python
# backend/app/rag/graph_builder.py
"""知识图谱构建管线：规则（wikilink + 相关知识章节）+ LLM 混合抽取 → kg.json。

设计依据：docs/superpowers/specs/2026-08-16-knowledge-graph-design.md
- 纯函数层（解析/对齐/规则边/合并）与 LLM 层分离，前者可离线单测
- raw 目录存在损坏文件（37 字节截断）与同名历史版本：
  正文 < MIN_BODY_CHARS 跳过；同名概念取内容更长者
- 图谱构建失败不阻塞索引重建（调用方 index.py try/except）
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import frontmatter
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

MIN_BODY_CHARS = 200  # 低于此长度的文档视为损坏/占位（如 37 字节历史残留文件）
RELATION_TYPES = ("依赖", "组成", "对比", "演进", "应用", "相关")
CATEGORIES = ("基础架构", "检索增强", "Agent工程", "提示工程", "训练与优化")

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_RELATED_HEADING_RE = re.compile(r"^##\s*.*相关知识\s*$", re.MULTILINE)


# ---------- LLM 结构化输出 schema ----------

class RelationItem(BaseModel):
    target: str
    type: Literal["依赖", "组成", "对比", "演进", "应用", "相关"]
    description: str = ""


class GraphExtractSchema(BaseModel):
    """单篇概念文档的 LLM 抽取结果。"""
    summary: str
    category: Literal["基础架构", "检索增强", "Agent工程", "提示工程", "训练与优化"]
    relations: list[RelationItem]


# ---------- 数据模型 ----------

@dataclass
class ConceptDoc:
    """概念词条原始文档（归一化前的解析结果）。"""
    file: str
    title: str
    aliases: list[str]
    tags: list[str]
    content: str


@dataclass
class Concept:
    """对齐后的概念节点。id 为 title 归一化结果，全图唯一。"""
    id: str
    title: str
    aliases: list[str]
    tags: list[str]
    file: str
    content: str
    summary: str = ""
    category: str = "基础架构"


# ---------- 纯函数层 ----------

def normalize_concept(name: str) -> str:
    """概念名归一化：去所有空白 + 小写。title/aliases/stem/wikilink 目标统一走此函数对齐。"""
    return re.sub(r"\s+", "", name).lower()


def parse_doc(path: Path) -> Optional[ConceptDoc]:
    """解析单篇 md。损坏（frontmatter 未闭合等）或正文过短的文件返回 None 跳过。"""
    try:
        post = frontmatter.load(path)
    except Exception:
        logger.warning("graph_builder: 解析失败跳过 %s", path.name)
        return None
    content = post.content.strip()
    if len(content) < MIN_BODY_CHARS:
        logger.info("graph_builder: 文档过短跳过 %s（%d 字）", path.name, len(content))
        return None
    meta = post.metadata or {}
    raw_tags = meta.get("tags", [])
    if isinstance(raw_tags, str):
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    else:
        tags = [str(t) for t in raw_tags]
    return ConceptDoc(
        file=path.name,
        title=str(meta.get("title") or path.stem),
        aliases=[str(a) for a in meta.get("aliases", [])],
        tags=tags,
        content=content,
    )


def align_concepts(docs: list[ConceptDoc]) -> tuple[dict[str, Concept], dict[str, str]]:
    """概念对齐：title 归一化为主键；同名概念（历史版本）取内容更长者。

    返回 (概念表, 别名→概念ID 映射)。aliases 与文件名 stem 也登记进别名映射，
    供 wikilink/"相关知识"条目的目标解析使用。
    """
    by_key: dict[str, Concept] = {}
    for d in sorted(docs, key=lambda x: len(x.content), reverse=True):
        cid = normalize_concept(d.title)
        if not cid or cid in by_key:
            continue  # 重复历史版本：已保留内容更长的那份
        by_key[cid] = Concept(
            id=cid, title=d.title, aliases=d.aliases, tags=d.tags,
            file=d.file, content=d.content,
        )
    alias_to_id: dict[str, str] = {}
    for c in by_key.values():
        for a in c.aliases:
            alias_to_id.setdefault(normalize_concept(a), c.id)
        stem = normalize_concept(Path(c.file).stem)
        if stem:
            alias_to_id.setdefault(stem, c.id)
    return by_key, alias_to_id


def extract_wikilinks(content: str) -> list[str]:
    """抽取全文 [[XXX]] / [[XXX|alias]] 的目标名（alias 形态取竖线前部分）。"""
    return _WIKILINK_RE.findall(content)


def extract_related_section(content: str) -> list[tuple[str, str]]:
    """解析"相关知识"章节：返回 [(概念名, 描述)]。

    定位 `## xxx相关知识` 标题，截取到下一个二级标题或文末；
    条目形如 `- [[LLM 大语言模型]] — Agent 的"大脑"基础`。
    """
    m = _RELATED_HEADING_RE.search(content)
    if not m:
        return []
    rest = content[m.end():]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    section = rest[: nxt.start()] if nxt else rest
    items: list[tuple[str, str]] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith(("-", "*")):
            continue
        lm = _WIKILINK_RE.search(line)
        if not lm:
            continue
        desc = line[lm.end():].lstrip(" —-—·").strip()
        items.append((lm.group(1), desc))
    return items


def resolve_target(raw: str, by_key: dict[str, Concept], alias_to_id: dict[str, str]) -> Optional[str]:
    """wikilink/条目目标 → 概念 ID。不在概念清单内返回 None（该边丢弃）。"""
    n = normalize_concept(raw)
    if n in by_key:
        return n
    return alias_to_id.get(n)


def _collect_rule_targets(content: str) -> list[tuple[str, str]]:
    """相关知识条目（带描述）优先，其余全文 wikilink 补充；同名去重。"""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, desc in extract_related_section(content):
        if name not in seen:
            seen.add(name)
            out.append((name, desc))
    for raw in extract_wikilinks(content):
        if raw not in seen:
            seen.add(raw)
            out.append((raw, ""))
    return out


def build_rule_edges(by_key: dict[str, Concept], alias_to_id: dict[str, str]) -> list[dict]:
    """规则边：wikilink + 相关知识章节 → type 恒为"相关"。

    无序对去重、丢弃未知目标与自环；描述取"相关知识"章节的破折号文本。
    """
    edges: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    for c in by_key.values():
        for raw, desc in _collect_rule_targets(c.content):
            tid = resolve_target(raw, by_key, alias_to_id)
            if not tid or tid == c.id:
                continue
            pair = tuple(sorted((c.id, tid)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append({
                "source": c.id, "target": tid,
                "type": "相关", "via": "rule", "description": desc,
            })
    return edges


def merge_edges(rule_edges: list[dict], llm_edges: list[dict]) -> list[dict]:
    """无序对合并：规则覆盖过的对 via 保持 rule（作者确认，可靠度更高），
    type/description 采用 LLM 的细分标注；LLM 独有的边 via=llm。"""
    by_pair: dict[tuple[str, str], dict] = {}
    for e in rule_edges:
        by_pair[tuple(sorted((e["source"], e["target"])))] = dict(e)
    for e in llm_edges:
        pair = tuple(sorted((e["source"], e["target"])))
        if pair in by_pair:
            merged = by_pair[pair]
            merged["type"] = e["type"]
            if e.get("description"):
                merged["description"] = e["description"]
        else:
            by_pair[pair] = {
                "source": e["source"], "target": e["target"],
                "type": e["type"], "via": "llm",
                "description": e.get("description", ""),
            }
    return list(by_pair.values())


def compute_degrees(nodes: list[dict], edges: list[dict]) -> None:
    """按合并后边数计算各节点度数（就地写入 degree 字段），前端据此定节点大小。"""
    for n in nodes:
        n["degree"] = 0
    for e in edges:
        for n in nodes:
            if n["id"] in (e["source"], e["target"]):
                n["degree"] += 1
```

- [ ] **Step 4: 语法检查（不跑测试）**

Run: `& d:\Project\Agent\backend\.venv\Scripts\python.exe -m py_compile d:\Project\Agent\backend\app\rag\graph_builder.py d:\Project\Agent\backend\app\config.py`
Expected: 无输出（退出码 0）

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/graph_builder.py backend/app/config.py backend/tests/unit/test_graph_builder.py
git commit -m "feat(graph): graph_builder 纯函数层（解析/对齐/规则边/合并/度数）"
```

---

### Task 2: graph_builder LLM 层与构建入口

**Files:**
- Modify: `backend/app/rag/graph_builder.py`（文件末尾追加）
- Modify: `backend/tests/unit/test_graph_builder.py`（末尾追加）

- [ ] **Step 1: 追加失败的单测**

在 `backend/tests/unit/test_graph_builder.py` 末尾追加：

```python
# ---------- LLM 层与构建入口 ----------

from unittest.mock import AsyncMock, patch

from app.rag.graph_builder import (
    build_extract_user_prompt,
    build_knowledge_graph,
    extract_concept_with_llm,
)


def _mini_kb(tmp_path):
    """两概念迷你知识库：A 的相关知识章节指向 B。"""
    pa = _write_md(
        tmp_path, "Agent.md", title="AI Agent 智能体", aliases=["智能体"],
        body="Agent 内容。" * 100 + "\n\n## 十、相关知识\n- [[RAG 检索增强生成]] — 外挂知识库\n",
    )
    pb = _write_md(tmp_path, "RAG.md", title="RAG 检索增强生成", body="RAG 内容。" * 100)
    return pa.parent


class TestExtractConceptWithLlm:
    async def _run(self, structured):
        p = _write_md(
            None, "x.md", title="AI Agent 智能体", aliases=["智能体"],
            body="正文" * 150,
        )
        d = parse_doc(p)
        by_key, alias_to_id = align_concepts([d])
        c = by_key[normalize_concept("AI Agent 智能体")]
        with patch("app.rag.graph_builder.call_llm", new=AsyncMock(
            return_value={"text": "", "structured": structured}
        )):
            return await extract_concept_with_llm(c, by_key, alias_to_id)

    @pytest.mark.asyncio
    async def test_normal_extraction(self):
        result = await self._run({
            "summary": "自主感知决策执行任务的智能系统",
            "category": "Agent工程",
            "relations": [{"target": "RAG 检索增强生成", "type": "依赖", "description": "外挂知识"}],
        })
        assert result["summary"] == "自主感知决策执行任务的智能系统"
        assert result["category"] == "Agent工程"
        assert result["relations"] == [
            {"target": "rag检索增强生成", "type": "依赖", "description": "外挂知识"}
        ]

    @pytest.mark.asyncio
    async def test_illegal_type_clamped_and_unknown_target_dropped(self):
        result = await self._run({
            "summary": "s",
            "category": "不存在的类",
            "relations": [
                {"target": "RAG 检索增强生成", "type": "乱写的关系", "description": "d"},
                {"target": "清单外概念", "type": "依赖", "description": "d"},
            ],
        })
        # 非法 type 兜底为"相关"；target 不在概念清单内被丢弃；非法 category 兜底
        assert result["category"] == "基础架构"
        assert result["relations"] == [
            {"target": "rag检索增强生成", "type": "相关", "description": "d"}
        ]

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        p = _write_md(None, "x.md", title="AI Agent 智能体", body="正文" * 150)
        d = parse_doc(p)
        by_key, alias_to_id = align_concepts([d])
        with patch("app.rag.graph_builder.call_llm", new=AsyncMock(
            side_effect=RuntimeError("重试耗尽")
        )):
            result = await extract_concept_with_llm(
                by_key[normalize_concept("AI Agent 智能体")], by_key, alias_to_id
            )
        assert result is None


class TestBuildExtractUserPrompt:
    def test_prompt_contains_id_list_and_content(self):
        c = Concept(
            id="agent", title="Agent", aliases=[], tags=[], file="a.md",
            content="文档内容" * 10,
        )
        prompt = build_extract_user_prompt(c, ["agent", "rag"])
        assert "agent、rag" in prompt
        assert "文档内容" in prompt


class TestBuildKnowledgeGraph:
    @pytest.mark.asyncio
    async def test_pipeline_writes_kg_json(self, tmp_path, monkeypatch):
        kb = _mini_kb(tmp_path / "raw")
        (tmp_path / "raw").mkdir(parents=True)
        # 重新写文件（_mini_kb 内部已 mkdir）
        kb = _mini_kb(tmp_path / "raw")
        out = tmp_path / "kg.json"
        monkeypatch.setattr(settings, "KB_DATA_DIR", str(kb))

        async def fake_extract(c, by_key, alias_to_id):
            return {
                "summary": f"{c.title} 的摘要",
                "category": "Agent工程",
                "relations": [
                    {"target": "rag检索增强生成", "type": "依赖", "description": "知识来源"}
                ] if c.id == "aiagent智能体" else [],
            }

        with patch("app.rag.graph_builder.extract_concept_with_llm", new=fake_extract):
            stats = await build_knowledge_graph(output_path=str(out))

        assert stats["nodes"] == 2
        kg = json.loads(out.read_text(encoding="utf-8"))
        assert set(kg.keys()) == {"built_at", "nodes", "edges"}
        ids = {n["id"] for n in kg["nodes"]}
        assert ids == {"aiagent智能体", "rag检索增强生成"}
        # 规则边被 LLM 边覆盖 type=依赖，via 保持 rule
        assert kg["edges"] == [{
            "source": "aiagent智能体", "target": "rag检索增强生成",
            "type": "依赖", "via": "rule", "description": "知识来源",
        }]
        by_id = {n["id"]: n for n in kg["nodes"]}
        assert by_id["aiagent智能体"]["summary"] == "AI Agent 智能体 的摘要"
        assert by_id["aiagent智能体"]["category"] == "Agent工程"
        assert by_id["aiagent智能体"]["degree"] == 1

    @pytest.mark.asyncio
    async def test_llm_failure_degrades_to_rule_edges(self, tmp_path, monkeypatch):
        kb = _mini_kb(tmp_path / "raw")
        out = tmp_path / "kg.json"
        monkeypatch.setattr(settings, "KB_DATA_DIR", str(kb))

        async def fake_extract(c, by_key, alias_to_id):
            return None  # 全部失败

        with patch("app.rag.graph_builder.extract_concept_with_llm", new=fake_extract):
            stats = await build_knowledge_graph(output_path=str(out))
        kg = json.loads(out.read_text(encoding="utf-8"))
        # LLM 全挂：规则边保留、summary 为空、category 兜底
        assert stats["nodes"] == 2
        assert kg["edges"][0]["type"] == "相关"
        assert kg["edges"][0]["description"] == "外挂知识库"
        assert all(n["summary"] == "" for n in kg["nodes"])
        assert all(n["category"] == "基础架构" for n in kg["nodes"])
```

注意：`_write_md(None, ...)` 传 `None` 时 tmp_path 不存在会报错——把 `_write_md` 的第一参改成允许 `tmp_path` 传目录 Path，测试里用 `tmp_path / "raw"`（先 mkdir）。实现时按此调整测试辅助函数（`_write_md(dir_path, ...)` 内部 `dir_path.mkdir(parents=True, exist_ok=True)`）。

- [ ] **Step 2: 实现 LLM 层与入口（graph_builder.py 末尾追加）**

在 `backend/app/rag/graph_builder.py` 顶部 import 区补充：

```python
from app.graph.tools import call_llm
```

文件末尾追加：

```python
# ---------- LLM 层 ----------

_LLM_CONTENT_CAP = 6000  # 单篇文档送 LLM 的字符上限（防超长文档撑爆 prompt）

_EXTRACT_SYSTEM_PROMPT = (
    "你是知识图谱构建专家。基于给定的 AI 概念文档内容，抽取概念摘要、所属大类、"
    "与其他概念的关系。\n"
    "严格要求：\n"
    "1. summary 为一句话概念摘要，不超过 50 字\n"
    "2. category 必须从给定枚举中选择\n"
    "3. relations.target 必须严格取自给定的概念 ID 清单，不得编造\n"
    "4. 关系必须以文档内容为依据，宁缺毋滥，最多 8 条\n"
)


def build_extract_user_prompt(c: Concept, concept_ids: list[str]) -> str:
    """构造抽取 prompt：概念 ID 清单 + 当前概念 + 截断后的文档内容。"""
    id_list = "、".join(concept_ids)
    return (
        f"概念 ID 清单（relations.target 只能从中选择）：{id_list}\n\n"
        f"当前概念：{c.title}（ID: {c.id}）\n\n"
        f"文档内容：\n{c.content[:_LLM_CONTENT_CAP]}"
    )


async def extract_concept_with_llm(
    c: Concept, by_key: dict[str, Concept], alias_to_id: dict[str, str]
) -> Optional[dict]:
    """单篇 LLM 抽取。call_llm 内部已有 3 次重试，重试耗尽返回 None（该篇降级）。

    返回值经净化：非法 category 兜底、非法 type 归"相关"、清单外 target 丢弃。
    """
    ids = list(by_key.keys())
    try:
        result = await call_llm(
            _EXTRACT_SYSTEM_PROMPT,
            build_extract_user_prompt(c, ids),
            temperature=0.2,
            output_schema=GraphExtractSchema,
            model=settings.MODEL_FLASH,
        )
    except Exception:
        logger.warning("graph_builder: LLM 抽取失败降级 %s", c.title, exc_info=True)
        return None
    structured = (result or {}).get("structured") or {}
    category = structured.get("category")
    if category not in CATEGORIES:
        category = "基础架构"
    relations: list[dict] = []
    for r in structured.get("relations", []):
        tid = resolve_target(str(r.get("target", "")), by_key, alias_to_id)
        if not tid or tid == c.id:
            continue
        rtype = r.get("type")
        if rtype not in RELATION_TYPES:
            rtype = "相关"
        relations.append({
            "target": tid, "type": rtype,
            "description": str(r.get("description", ""))[:30],
        })
    return {
        "summary": str(structured.get("summary", ""))[:60],
        "category": category,
        "relations": relations,
    }


# ---------- 构建入口 ----------

async def build_knowledge_graph(output_path: Optional[str] = None) -> dict:
    """完整管线：扫描 raw → 对齐 → 规则边 → LLM 抽取 → 合并 → 写 kg.json。

    供 index.py 在索引重建成功后调用；异常向上抛（调用方决定是否阻塞）。
    """
    raw_dir = Path(settings.KB_DATA_DIR)
    out = Path(output_path or settings.KG_JSON_PATH)

    docs: list[ConceptDoc] = []
    for p in sorted(raw_dir.glob("*.md")):
        d = parse_doc(p)
        if d:
            docs.append(d)
    by_key, alias_to_id = align_concepts(docs)
    rule_edges = build_rule_edges(by_key, alias_to_id)

    llm_edges: list[dict] = []
    for c in by_key.values():
        extracted = await extract_concept_with_llm(c, by_key, alias_to_id)
        if not extracted:
            continue
        c.summary = extracted["summary"]
        c.category = extracted["category"]
        for r in extracted["relations"]:
            llm_edges.append({
                "source": c.id, "target": r["target"],
                "type": r["type"], "via": "llm", "description": r["description"],
            })

    edges = merge_edges(rule_edges, llm_edges)
    nodes = [
        {
            "id": c.id, "title": c.title, "aliases": c.aliases,
            "summary": c.summary, "category": c.category,
            "tags": c.tags, "file": c.file, "degree": 0,
        }
        for c in by_key.values()
    ]
    compute_degrees(nodes, edges)

    kg = {"built_at": datetime.now().isoformat(), "nodes": nodes, "edges": edges}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("graph_builder: %d 节点 %d 边 → %s", len(nodes), len(edges), out)
    return {"nodes": len(nodes), "edges": len(edges)}
```

- [ ] **Step 3: 语法检查（不跑测试）**

Run: `& d:\Project\Agent\backend\.venv\Scripts\python.exe -m py_compile d:\Project\Agent\backend\app\rag\graph_builder.py`
Expected: 无输出（退出码 0）

- [ ] **Step 4: Commit**

```bash
git add backend/app/rag/graph_builder.py backend/tests/unit/test_graph_builder.py
git commit -m "feat(graph): LLM 抽取层与 build_knowledge_graph 入口（净化/降级/写盘）"
```

---

### Task 3: GET /api/graph + rebuild 挂钩

**Files:**
- Create: `backend/app/api/graph.py`
- Modify: `backend/app/main.py:146-154`（注册路由）
- Modify: `backend/app/models/schemas.py:43-45`（IndexRebuildResponse 加 graph_built）
- Modify: `backend/app/api/index.py:23-33`（rebuild 挂钩）
- Modify: `backend/tests/integration/test_api_index.py`（既有用例补 patch + 断言）
- Create: `backend/tests/integration/test_api_graph.py`

- [ ] **Step 1: 写失败的集成测试**

创建 `backend/tests/integration/test_api_graph.py`：

```python
# backend/tests/integration/test_api_graph.py
"""GET /api/graph 集成测试：404 / 200+ETag / 304 / 损坏 JSON。"""
import json

import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from app.main import app
from app.config import settings

KG_SAMPLE = {
    "built_at": "2026-08-16T12:00:00",
    "nodes": [
        {"id": "agent", "title": "Agent", "summary": "s", "category": "Agent工程",
         "tags": ["AI"], "file": "a.md", "degree": 1, "aliases": []},
        {"id": "rag", "title": "RAG", "summary": "s", "category": "检索增强",
         "tags": ["AI"], "file": "r.md", "degree": 1, "aliases": []},
    ],
    "edges": [
        {"source": "agent", "target": "rag", "type": "依赖", "via": "rule", "description": ""},
    ],
}


async def _get(client, headers=None):
    return await client.get("/api/graph", headers=headers or {})


@pytest.mark.asyncio
async def test_graph_404_when_not_built(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KG_JSON_PATH", str(tmp_path / "absent.json"))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await _get(c)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "knowledge graph not built"


@pytest.mark.asyncio
async def test_graph_200_with_etag(tmp_path, monkeypatch):
    kg = tmp_path / "kg.json"
    kg.write_text(json.dumps(KG_SAMPLE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings, "KG_JSON_PATH", str(kg))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await _get(c)
    assert resp.status_code == 200
    assert resp.json() == KG_SAMPLE
    etag = resp.headers["etag"]
    assert etag  # built_at 哈希

    # 同 ETag 再请求 → 304
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp304 = await _get(c, headers={"If-None-Match": etag})
    assert resp304.status_code == 304


@pytest.mark.asyncio
async def test_graph_500_when_corrupted(tmp_path, monkeypatch):
    kg = tmp_path / "kg.json"
    kg.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(settings, "KG_JSON_PATH", str(kg))
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await _get(c)
    assert resp.status_code == 500
```

同时修改 `backend/tests/integration/test_api_index.py` 的既有用例（rebuild 现在会触发图谱构建，必须 patch 掉避免真实 LLM 调用），并追加 2 个新用例：

```python
# backend/tests/integration/test_api_index.py
import pytest
from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager
from unittest.mock import patch, MagicMock, AsyncMock
from app.main import app


@pytest.mark.asyncio
async def test_rebuild_index():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            with patch("app.api.index.get_indexer") as mock_get, \
                 patch("app.api.index.build_knowledge_graph", new_callable=AsyncMock) as mock_graph:
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
    assert data["graph_built"] is True
    mock_graph.assert_awaited_once()


@pytest.mark.asyncio
async def test_rebuild_index_graph_failure_not_blocking():
    """图谱构建失败不阻塞索引重建：graph_built=False 但整体仍 success。"""
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            with patch("app.api.index.get_indexer") as mock_get, \
                 patch("app.api.index.build_knowledge_graph", new_callable=AsyncMock) as mock_graph:
                mock_idx = MagicMock()
                mock_idx.build = MagicMock()
                mock_idx.chroma_collection = MagicMock()
                mock_idx.chroma_collection.count = MagicMock(return_value=18)
                mock_get.return_value = mock_idx
                mock_graph.side_effect = RuntimeError("LLM 全挂")

                resp = await c.post("/api/index/rebuild")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["graph_built"] is False
```

（原文件的 `test_rebuild_index` 用例整体替换为上述第一个用例——仅增加 graph patch 与 2 行断言，其余逻辑不变。）

- [ ] **Step 2: 实现 schemas.py**

`backend/app/models/schemas.py:43-45` 改为：

```python
class IndexRebuildResponse(BaseModel):
    success: bool
    doc_count: int
    # 知识图谱构建结果（构建失败不阻塞索引，仅置 False，前端可提示重建）
    graph_built: bool = True
```

- [ ] **Step 3: 实现 api/graph.py**

创建 `backend/app/api/graph.py`：

```python
# backend/app/api/graph.py
"""知识图谱只读 API：读 kg.json 原样返回，支持 ETag/304。"""
import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(prefix="/api/graph", tags=["graph"])
logger = logging.getLogger(__name__)


@router.get("")
async def get_graph(request: Request):
    path = Path(settings.KG_JSON_PATH)
    if not path.exists():
        raise HTTPException(status_code=404, detail="knowledge graph not built")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.error("kg.json 解析失败", exc_info=True)
        raise HTTPException(status_code=500, detail="knowledge graph data corrupted")

    # ETag 取 built_at 哈希：重建后指纹变化，客户端缓存自动失效
    etag = f'W/"{hashlib.md5(str(data.get("built_at", "")).encode()).hexdigest()}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(data, headers={"ETag": etag})
```

- [ ] **Step 4: main.py 注册路由**

`backend/app/main.py` 第 146-154 行区域，在 `app.include_router(index_api.router)` 之后加：

```python
from app.api import graph as graph_api  # noqa: E402

app.include_router(graph_api.router)
```

- [ ] **Step 5: index.py 挂钩**

`backend/app/api/index.py` 整体改为：

```python
# backend/app/api/index.py
import logging

from fastapi import APIRouter, HTTPException, Request
from app.models.schemas import IndexRebuildResponse
from app.rag.indexer import Indexer
from app.rag.graph_builder import build_knowledge_graph
from app.extensions import limiter

router = APIRouter(prefix="/api/index", tags=["index"])

logger = logging.getLogger(__name__)

_indexer: Indexer = None


def set_indexer(indexer: Indexer) -> None:
    global _indexer
    _indexer = indexer


def get_indexer() -> Indexer:
    if _indexer is None:
        raise RuntimeError("Indexer not initialized")
    return _indexer


@router.post("/rebuild", response_model=IndexRebuildResponse)
@limiter.limit("1/minute")
async def rebuild_index(request: Request):
    # 直接调用 get_indexer()，不使用 Depends，便于测试 monkeypatch 生效
    indexer = get_indexer()
    try:
        indexer.build()
        doc_count = indexer.chroma_collection.count()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"索引重建失败: {e}")

    # 索引成功后构建知识图谱；失败不阻塞索引，仅标记 graph_built=False
    graph_built = True
    try:
        await build_knowledge_graph()
    except Exception:
        logger.warning("知识图谱构建失败（不影响索引）", exc_info=True)
        graph_built = False

    return IndexRebuildResponse(success=True, doc_count=doc_count, graph_built=graph_built)
```

（模块级 import `build_knowledge_graph` 便于测试 `patch("app.api.index.build_knowledge_graph")`。）

- [ ] **Step 6: 语法检查（不跑测试）**

Run: `& d:\Project\Agent\backend\.venv\Scripts\python.exe -m py_compile backend/app/api/graph.py backend/app/api/index.py backend/app/models/schemas.py backend/app/main.py`
Expected: 无输出（退出码 0）

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/graph.py backend/app/main.py backend/app/models/schemas.py backend/app/api/index.py backend/tests/integration/test_api_graph.py backend/tests/integration/test_api_index.py
git commit -m "feat(graph): GET /api/graph（ETag/304）+ 索引重建挂钩图谱构建（失败不阻塞）"
```

---

### Task 4: 前端基础设施（echarts 依赖 + 类型 + API + option 构建器 + ask 工具）

**Files:**
- Modify: `frontend/package.json`（npm i echarts）
- Modify: `frontend/src/types/index.ts`（末尾追加）
- Create: `frontend/src/api/graph.ts`
- Create: `frontend/src/utils/graphOption.ts`
- Create: `frontend/src/utils/askQuery.ts`
- Create: `frontend/src/utils/__tests__/graphOption.test.ts`
- Create: `frontend/src/utils/__tests__/askQuery.test.ts`

- [ ] **Step 1: 安装 echarts**

Run: `cd frontend && npm install echarts@^5`
Expected: package.json dependencies 出现 `"echarts": "^5.x.x"`

- [ ] **Step 2: 类型定义**

`frontend/src/types/index.ts` 末尾（StreamCallbacks 之后）追加：

```ts
// 知识图谱（GET /api/graph）
export interface GraphNode {
  id: string
  title: string
  summary: string
  category: string
  tags: string[]
  file: string
  degree: number
  aliases?: string[]
}

export interface GraphEdge {
  source: string
  target: string
  type: string
  via: 'rule' | 'llm'
  description?: string
}

export interface GraphData {
  built_at: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}
```

- [ ] **Step 3: api/graph.ts**

```ts
// frontend/src/api/graph.ts
// 知识图谱 API：读 kg.json / 触发重建（复用索引重建接口，1/min 限速）。
import type { GraphData } from '@/types'

export class GraphNotBuiltError extends Error {
  constructor() {
    super('knowledge graph not built')
    this.name = 'GraphNotBuiltError'
  }
}

export async function fetchGraph(): Promise<GraphData> {
  const r = await fetch('/api/graph')
  if (r.status === 404) throw new GraphNotBuiltError()
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()) as GraphData
}

export interface RebuildResult {
  success: boolean
  doc_count: number
  graph_built: boolean
}

export async function rebuildIndex(): Promise<RebuildResult> {
  const r = await fetch('/api/index/rebuild', { method: 'POST' })
  if (r.status === 429) throw new Error('重建请求过于频繁，请稍后再试')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()) as RebuildResult
}
```

- [ ] **Step 4: utils/graphOption.ts（纯函数，可单测）**

```ts
// frontend/src/utils/graphOption.ts
// ECharts 力导向图 option 构建器（纯函数，与组件解耦便于单测）。
import type { GraphData } from '@/types'

/** 5 个大类的固定配色（图例 + 节点着色共用） */
export const CATEGORY_COLORS: Record<string, string> = {
  基础架构: '#6366f1',
  检索增强: '#f59e0b',
  Agent工程: '#10b981',
  提示工程: '#ec4899',
  训练与优化: '#06b6d4',
}

/** 结构性关系（实线）；对比/相关为弱关系（虚线） */
export const STRUCTURAL_TYPES = ['依赖', '组成', '应用', '演进']

/** 度数 → 节点大小（20-60px），前端渲染前已由后端算好 degree */
export function degreeToSize(degree: number): number {
  return Math.min(60, 20 + degree * 6)
}

interface GraphParams {
  dataType: string
  data: Record<string, unknown>
}

export function buildGraphOption(data: GraphData): Record<string, unknown> {
  const categoryNames = Object.keys(CATEGORY_COLORS)
  const catIndex = new Map(categoryNames.map((n, i) => [n, i]))

  const nodes = data.nodes.map((n) => ({
    id: n.id,
    name: n.title,
    category: catIndex.get(n.category) ?? 0,
    symbolSize: degreeToSize(n.degree),
    value: n.degree,
  }))

  const links = data.edges.map((e) => ({
    source: e.source,
    target: e.target,
    type: e.type,
    description: e.description ?? '',
    lineStyle: {
      type: STRUCTURAL_TYPES.includes(e.type) ? ('solid' as const) : ('dashed' as const),
      color: '#d6d3d1',
      width: 1.5,
      curveness: 0.15,
    },
  }))

  return {
    backgroundColor: '#fafaf9',
    tooltip: {
      confine: true,
      formatter: (params: GraphParams) => {
        if (params.dataType === 'edge') {
          const d = params.data
          const desc = d.description ? `：${d.description}` : ''
          return `${d.type}${desc}`
        }
        if (params.dataType === 'node') {
          return `${params.data.name}（${params.data.value} 条关联）`
        }
        return ''
      },
    },
    legend: [
      {
        data: categoryNames,
        bottom: 12,
        icon: 'circle',
        itemWidth: 10,
        textStyle: { color: '#57534e', fontSize: 11 },
      },
    ],
    series: [
      {
        type: 'graph',
        layout: 'force',
        force: {
          repulsion: 320,
          edgeLength: [90, 170],
          gravity: 0.08,
          layoutAnimation: true,
        },
        roam: true,
        draggable: true,
        categories: categoryNames.map((n) => ({
          name: n,
          itemStyle: { color: CATEGORY_COLORS[n] },
        })),
        data: nodes,
        links,
        label: { show: true, position: 'bottom', fontSize: 11, color: '#44403c' },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
        lineStyle: { opacity: 0.8 },
      },
    ],
  }
}
```

- [ ] **Step 5: utils/askQuery.ts**

```ts
// frontend/src/utils/askQuery.ts
// 知识图谱"一键提问"的落地逻辑：消费 ?ask= 参数，自动发送并清除。
// 抽为纯工具便于单测（route/router/store 由调用方注入）。
interface AskRouteLike {
  query: { ask?: unknown }
}
interface AskRouterLike {
  replace: (to: { query: Record<string, unknown> }) => Promise<unknown>
}
interface AskStoreLike {
  inputText: string
  sendMessage: () => Promise<void>
}

export async function consumeAskQuery(
  route: AskRouteLike,
  router: AskRouterLike,
  store: AskStoreLike
): Promise<boolean> {
  const ask = route.query.ask
  if (typeof ask !== 'string' || !ask.trim()) return false
  store.inputText = ask.trim()
  await store.sendMessage()
  // 清除 query 参数，防刷新重发
  await router.replace({ query: {} })
  return true
}
```

- [ ] **Step 6: 写单测（暂不运行）**

创建 `frontend/src/utils/__tests__/graphOption.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import { buildGraphOption, CATEGORY_COLORS, degreeToSize, STRUCTURAL_TYPES } from '@/utils/graphOption'
import type { GraphData } from '@/types'

const data: GraphData = {
  built_at: '2026-08-16T00:00:00',
  nodes: [
    { id: 'a', title: 'Agent', summary: '', category: 'Agent工程', tags: [], file: 'a.md', degree: 3 },
    { id: 'b', title: 'RAG', summary: '', category: '检索增强', tags: [], file: 'b.md', degree: 1 },
    { id: 'c', title: '未知类', summary: '', category: '其他', tags: [], file: 'c.md', degree: 0 },
  ],
  edges: [
    { source: 'a', target: 'b', type: '依赖', via: 'rule' },
    { source: 'a', target: 'c', type: '相关', via: 'llm', description: '弱关联' },
  ],
}

describe('degreeToSize', () => {
  it('maps degree to size with 60px cap', () => {
    expect(degreeToSize(0)).toBe(20)
    expect(degreeToSize(3)).toBe(38)
    expect(degreeToSize(10)).toBe(60) // 封顶
  })
})

describe('buildGraphOption', () => {
  const option = buildGraphOption(data) as {
    series: Array<{ data: Array<Record<string, unknown>>; links: Array<Record<string, unknown>> }>
    legend: Array<{ data: string[] }>
  }

  it('maps nodes with category index and degree size', () => {
    const a = option.series[0].data.find((n) => n.id === 'a')
    expect(a?.category).toBe(2) // Agent工程 在 CATEGORY_COLORS 第 3 位
    expect(a?.symbolSize).toBe(38)
    // 未知大类兜底为第 0 类（基础架构）
    const c = option.series[0].data.find((n) => n.id === 'c')
    expect(c?.category).toBe(0)
  })

  it('solid for structural types, dashed for weak', () => {
    const [dep, rel] = option.series[0].links
    expect(dep.lineStyle).toMatchObject({ type: 'solid' })
    expect(rel.lineStyle).toMatchObject({ type: 'dashed' })
    expect(rel.description).toBe('弱关联') // tooltip 数据随边携带
  })

  it('legend covers all five categories', () => {
    expect(option.legend[0].data).toEqual(Object.keys(CATEGORY_COLORS))
    expect(STRUCTURAL_TYPES).toContain('依赖')
  })
})
```

创建 `frontend/src/utils/__tests__/askQuery.test.ts`：

```ts
import { describe, expect, it, vi } from 'vitest'
import { consumeAskQuery } from '@/utils/askQuery'

function makeMocks(ask: unknown) {
  return {
    route: { query: { ask } },
    router: { replace: vi.fn().mockResolvedValue(undefined) },
    store: { inputText: '', sendMessage: vi.fn().mockResolvedValue(undefined) },
  }
}

describe('consumeAskQuery', () => {
  it('fills input, sends, then clears query param', async () => {
    const { route, router, store } = makeMocks('详细介绍「RAG 检索增强生成」')
    const consumed = await consumeAskQuery(route, router, store)
    expect(consumed).toBe(true)
    expect(store.inputText).toBe('详细介绍「RAG 检索增强生成」')
    expect(store.sendMessage).toHaveBeenCalledOnce()
    expect(router.replace).toHaveBeenCalledWith({ query: {} })
  })

  it('no-op when ask missing / empty / non-string', async () => {
    for (const ask of [undefined, '', '   ', 123]) {
      const { route, router, store } = makeMocks(ask)
      expect(await consumeAskQuery(route, router, store)).toBe(false)
      expect(store.sendMessage).not.toHaveBeenCalled()
      expect(router.replace).not.toHaveBeenCalled()
    }
  })
})
```

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/types/index.ts frontend/src/api/graph.ts frontend/src/utils/graphOption.ts frontend/src/utils/askQuery.ts frontend/src/utils/__tests__
git commit -m "feat(graph): 前端基础设施（echarts 按需引入类型/API/option 构建器/ask 工具）"
```

---

### Task 5: GraphView 页面 + 路由 + 入口 + ChatView 集成

**Files:**
- Create: `frontend/src/views/GraphView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/AppHeader.vue`（顶部导航加入口）
- Modify: `frontend/src/views/ChatView.vue:13-20`（onMounted 消费 ask）

- [ ] **Step 1: 创建 GraphView.vue**

```vue
<!-- frontend/src/views/GraphView.vue -->
<!-- 知识图谱页：力导向图 + 侧边概念卡片 + 一键提问闭环。
     设计依据：docs/superpowers/specs/2026-08-16-knowledge-graph-design.md -->
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ArrowLeft, RefreshCw, Send, X } from 'lucide-vue-next'
import { fetchGraph, rebuildIndex, GraphNotBuiltError } from '@/api/graph'
import { buildGraphOption, CATEGORY_COLORS } from '@/utils/graphOption'
import type { GraphData, GraphNode } from '@/types'

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer])

const router = useRouter()

const loading = ref(true)
const notBuilt = ref(false)
const loadError = ref('')
const rebuilding = ref(false)
const data = ref<GraphData | null>(null)
const selected = ref<GraphNode | null>(null)

const containerRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null

/** 选中概念的相邻概念（含关系类型），供卡片列表点击切换 */
const neighbors = computed(() => {
  if (!data.value || !selected.value) return [] as { node: GraphNode; type: string }[]
  const byId = new Map(data.value.nodes.map((n) => [n.id, n]))
  const sid = selected.value.id
  return data.value.edges
    .filter((e) => e.source === sid || e.target === sid)
    .map((e) => {
      const otherId = e.source === sid ? e.target : e.source
      return { node: byId.get(otherId), type: e.type }
    })
    .filter((x): x is { node: GraphNode; type: string } => Boolean(x.node))
})

async function load(): Promise<void> {
  loading.value = true
  notBuilt.value = false
  loadError.value = ''
  try {
    data.value = await fetchGraph()
    renderChart()
  } catch (e) {
    if (e instanceof GraphNotBuiltError) notBuilt.value = true
    else loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function renderChart(): void {
  if (!containerRef.value || !data.value) return
  if (!chart) {
    chart = echarts.init(containerRef.value)
    chart.on('click', (params) => {
      if (params.dataType === 'node') {
        selected.value =
          data.value?.nodes.find((n) => n.id === (params.data as { id?: string }).id) ?? null
      }
    })
  }
  chart.setOption(buildGraphOption(data.value))
}

async function onRebuild(): Promise<void> {
  rebuilding.value = true
  try {
    const r = await rebuildIndex()
    if (!r.graph_built) loadError.value = '图谱构建未完成，请稍后重试'
    await load()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    rebuilding.value = false
  }
}

function focusNeighbor(n: GraphNode): void {
  selected.value = n
}

function askAgent(n: GraphNode): void {
  const aliases = n.aliases?.length ? `（${n.aliases.join('、')}）` : ''
  router.push({ path: '/chat', query: { ask: `详细介绍「${n.title}」${aliases}` } })
}

onMounted(() => {
  load()
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(containerRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="flex flex-col h-full w-full bg-stone-50">
    <!-- 顶栏 -->
    <header class="h-14 border-b border-gray-200/80 bg-white/90 backdrop-blur flex items-center gap-3 px-4 shrink-0">
      <button
        @click="router.push('/chat')"
        class="flex items-center gap-1.5 text-xs text-gray-500 hover:text-stone-800 transition-colors"
      >
        <ArrowLeft class="w-3.5 h-3.5" /> 返回对话
      </button>
      <h1 class="text-sm font-semibold text-stone-800">知识图谱</h1>
      <span v-if="data" class="text-xs text-gray-400">
        {{ data.nodes.length }} 个概念 · {{ data.edges.length }} 条关系
      </span>
    </header>

    <div class="flex-1 flex min-h-0">
      <!-- 图谱画布 -->
      <div ref="containerRef" class="flex-1 min-w-0" />

      <!-- 加载 / 空态 / 错误 -->
      <div
        v-if="loading || notBuilt || loadError"
        class="absolute inset-0 flex items-center justify-center bg-stone-50/80 z-10"
      >
        <div v-if="loading" class="text-sm text-gray-400">图谱加载中...</div>
        <div v-else-if="notBuilt" class="text-center space-y-3">
          <p class="text-sm text-gray-500">知识图谱尚未构建</p>
          <p class="text-xs text-gray-400">重建知识库索引后将自动生成概念关系图谱</p>
          <button
            @click="onRebuild"
            :disabled="rebuilding"
            class="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-stone-800 text-white text-xs font-medium hover:bg-stone-700 disabled:opacity-50 transition-colors"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': rebuilding }" />
            {{ rebuilding ? '重建中（含 18 次 LLM 抽取，约 1-2 分钟）' : '重建知识库' }}
          </button>
        </div>
        <div v-else class="text-center space-y-2">
          <p class="text-sm text-red-500">{{ loadError }}</p>
          <button @click="load" class="text-xs text-gray-500 hover:text-stone-800">重试</button>
        </div>
      </div>

      <!-- 侧边概念卡片 -->
      <Transition
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="translate-x-full"
        leave-active-class="transition duration-150 ease-in"
        leave-to-class="translate-x-full"
      >
        <aside
          v-if="selected"
          class="w-72 shrink-0 border-l border-gray-200 bg-white p-4 space-y-3 overflow-y-auto"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <h2 class="text-sm font-semibold text-stone-800">{{ selected.title }}</h2>
              <span
                class="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] text-white"
                :style="{ backgroundColor: CATEGORY_COLORS[selected.category] ?? '#a8a29e' }"
              >
                {{ selected.category }}
              </span>
            </div>
            <button @click="selected = null" class="text-gray-400 hover:text-stone-700">
              <X class="w-4 h-4" />
            </button>
          </div>

          <p v-if="selected.summary" class="text-xs text-gray-600 leading-relaxed">
            {{ selected.summary }}
          </p>
          <div v-else class="flex flex-wrap gap-1">
            <span
              v-for="t in selected.tags"
              :key="t"
              class="px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 text-[10px]"
            >
              {{ t }}
            </span>
          </div>

          <div v-if="neighbors.length" class="space-y-1.5">
            <h3 class="text-[10px] font-medium text-gray-400 uppercase tracking-wide">相邻概念</h3>
            <button
              v-for="nb in neighbors"
              :key="nb.node.id"
              @click="focusNeighbor(nb.node)"
              class="flex items-center justify-between w-full px-2 py-1.5 rounded-md hover:bg-stone-50 text-left transition-colors"
            >
              <span class="text-xs text-gray-700 truncate">{{ nb.node.title }}</span>
              <span class="text-[10px] text-gray-400 shrink-0 ml-2">{{ nb.type }}</span>
            </button>
          </div>

          <div class="pt-2 border-t border-gray-100 space-y-2">
            <button
              @click="askAgent(selected)"
              class="flex items-center justify-center gap-1.5 w-full px-3 py-2 rounded-lg bg-amber-600 text-white text-xs font-medium hover:bg-amber-700 transition-colors"
            >
              <Send class="w-3.5 h-3.5" /> 向 Agent 提问
            </button>
            <p class="text-[10px] text-gray-400 text-center">来源：{{ selected.file }}</p>
          </div>
        </aside>
      </Transition>
    </div>
  </div>
</template>
```

- [ ] **Step 2: 路由（懒加载，echarts 体积大不进主 chunk）**

`frontend/src/router/index.ts` 改为：

```ts
// frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat', name: 'chat', component: ChatView },
    { path: '/chat/:id', name: 'chat-with-id', component: ChatView },
    // 知识图谱：懒加载（echarts ~1MB，避免拖慢聊天首屏）
    { path: '/graph', name: 'graph', component: () => import('@/views/GraphView.vue') },
  ],
})
```

- [ ] **Step 3: AppHeader 加图谱入口**

`frontend/src/components/AppHeader.vue`：

(a) script 的 lucide import 行改为：

```ts
import { Pencil, Network } from 'lucide-vue-next'
```

(b) template 中 `</header>` 之前（即左侧 div 闭合后）追加右侧导航：

```vue
    <!-- 知识图谱入口 -->
    <nav class="flex items-center gap-2 shrink-0">
      <RouterLink
        to="/graph"
        class="flex items-center gap-1.5 text-xs text-gray-500 hover:text-stone-800 border border-gray-200 hover:border-stone-300 rounded-lg px-2.5 py-1.5 transition-colors"
        title="概念知识图谱"
      >
        <Network class="w-3.5 h-3.5" /> 知识图谱
      </RouterLink>
    </nav>
  </header>
```

（header 已有 `justify-between`，左侧组之后追加此 nav 即自动靠右。）

- [ ] **Step 4: ChatView 消费 ask 参数**

`frontend/src/views/ChatView.vue` 的 script 改为：

```ts
<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { consumeAskQuery } from '@/utils/askQuery'
import ConversationSidebar from '@/components/ConversationSidebar.vue'
import ChatPanel from '@/components/ChatPanel.vue'

const route = useRoute()
const router = useRouter()
const store = useChatStore()

onMounted(async () => {
  await store.loadConversations()
  // 如果 URL 带 id，选中对应会话
  const id = route.params.id as string | undefined
  if (id && store.conversations.some((c) => c.id === id)) {
    await store.selectConversation(id)
  }
  // 知识图谱"一键提问"：检测 ?ask= 自动填入并发送（发送后清除参数防刷新重发）
  await consumeAskQuery(route, router, store)
})

// 监听 currentConversationId 变化，同步到 URL（可选，便于分享）
watch(
  () => store.currentConversationId,
  (newId) => {
    if (newId && route.params.id !== newId) {
      router.replace({ name: 'chat-with-id', params: { id: newId } }).catch(() => {})
    }
  }
)
</script>
```

（spec 原文写在 ChatPanel，实际放 ChatView：它已持有 route/router/store，避免重复注入。行为不变。）

- [ ] **Step 5: 类型检查兜底（不跑测试套件）**

Run: `cd frontend && npx vue-tsc -b --noEmit 2>&1 | head -30`
Expected: 无新增类型错误（echarts 类型自带）

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/GraphView.vue frontend/src/router/index.ts frontend/src/components/AppHeader.vue frontend/src/views/ChatView.vue
git commit -m "feat(graph): GraphView 力导向图页面 + /graph 路由 + 一键提问闭环"
```

---

### Task 6: 统一测试与手动验收（最后执行）

**Files:** 无新增

- [ ] **Step 1: 后端全量测试**

Run: `& d:\Project\Agent\backend\.venv\Scripts\python.exe -m pytest backend/tests -q`（仓库根执行）
Expected: 全部 PASS（含功能一 trace 测试 + 功能二 graph_builder/api_graph/api_index 测试）

- [ ] **Step 2: 前端全量测试 + 构建**

Run: `cd frontend && npm run test && npm run build`
Expected: vitest 全部 PASS；`vue-tsc -b && vite build` 成功

- [ ] **Step 3: 手动验收（启动前后端）**

1. `POST /api/index/rebuild`（或前端空态按钮）→ 观察后端日志 18 次 LLM 抽取 → `backend/data/kg.json` 生成，约 18 节点 / 数十条边
2. 访问 `/graph` → 力导向图入场动画、图例 5 类筛选、hover 高亮相邻、边 tooltip 显示类型+描述
3. 点击节点 → 侧边卡片（summary/category 徽章/相邻概念列表）；点击相邻概念切换卡片
4. 点"向 Agent 提问" → 跳 `/chat?ask=详细介绍「XX」` → 自动发送 → **TraceTimeline 思考过程可视化接管**（两功能闭环验证点）
5. 刷新聊天页 → 不重发（ask 参数已清除）
6. 删除 kg.json 重启 → `/graph` 空态 + 重建按钮；重建期间 429 限速提示
7. 聊天主流程回归：普通提问路径 trace 正常

- [ ] **Step 4: 验收微调提交（如有）**

```bash
git add -A
git commit -m "fix(graph): 手动验收微调"
```

---

## Self-Review 记录

- **Spec 覆盖**：混合抽取管线（Task 1/2）、概念对齐+损坏文件处理（Task 1，实测 37 字节文件与同名旧版均有对应规则与测试）、kg.json schema 含 aliases（一键提问别名拼接需要，spec 节点示例未列但 5.4 依赖）、`GET /api/graph` 404/ETag/304（Task 3）、rebuild 挂钩失败不阻塞（Task 3）、ECharts 按需引入+力导向+图例+邻接高亮+实虚线（Task 4/5）、侧边卡片含 summary 降级 tags（Task 5）、一键提问与参数清除（Task 4/5）、空态重建复用限速接口（Task 5）——全部覆盖。
- **有意偏差（已注明理由）**：ask 消费逻辑从 spec 的 ChatPanel 移到 ChatView（已持有 route/router/store）；边携带 description 字段（spec 5.2 边 tooltip 需要，产物 schema 补充）。
- **类型一致性**：`GraphNode/GraphEdge/GraphData`（types）↔ kg.json 产物（graph_builder）↔ api/graph.ts ↔ graphOption.ts ↔ GraphView.vue 全链路字段对齐；`graph_built: bool = True` 默认值保证旧响应兼容。
- **占位符扫描**：无 TBD/TODO，所有代码步骤含完整代码。
- **风险点**：DeepSeek function_calling 对 Literal 枚举的遵守度（extract_concept_with_llm 已做净化兜底，非法值不影响产物正确性）；18 次 LLM 顺序调用约 1-2 分钟（UI 已提示，可接受）。
