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
from app.graph.tools import call_llm

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
