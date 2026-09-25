# backend/app/rag/graph_builder.py
"""知识图谱构建管线：规则（wikilink + 相关知识章节）+ LLM 混合抽取 → kg.json。

设计依据：docs/superpowers/specs/2026-08-16-knowledge-graph-design.md
- 纯函数层（解析/对齐/规则边/合并）与 LLM 层分离，前者可离线单测
- raw 目录存在损坏文件（37 字节截断）与同名历史版本：
  正文 < MIN_BODY_CHARS 跳过；同名概念取内容更长者
- 图谱构建失败不阻塞索引重建（调用方 index.py try/except）
"""
# 导入 json，用于序列化写入 kg.json
import json
# 导入日志模块
import logging
# 导入正则模块，用于 wikilink/标题解析
import re
# 导入 dataclass 装饰器，用于定义纯数据模型
from dataclasses import dataclass
# 导入 datetime，用于生成图谱构建时间戳
from datetime import datetime
# 导入 Path，用于路径与文件名操作
from pathlib import Path
# 导入类型标注：Literal（限定取值）、Optional（可空）
from typing import Literal, Optional

# 导入 frontmatter，用于解析 md 前置元数据
import frontmatter
# 导入 pydantic 基类，用于定义 LLM 结构化输出的 schema
from pydantic import BaseModel

# 导入全局配置与知识库 profile 解析
from app.config import settings, resolve_kb_profile
# 导入 LLM 调用工具（内部含重试）
from app.graph.tools import call_llm
# 导入知识库 Markdown 遍历函数（obsidian 顶层 / drone 递归 + 排除清单）
from app.rag.readers import iter_kb_markdown_files

# 获取当前模块日志器
logger = logging.getLogger(__name__)

MIN_BODY_CHARS = 200  # 低于此长度的文档视为损坏/占位（如 37 字节历史残留文件）
RELATION_TYPES = ("依赖", "组成", "对比", "演进", "应用", "相关")  # 合法的关系类型枚举
CATEGORIES = ("基础架构", "检索增强", "Agent工程", "提示工程", "训练与优化")  # 合法的大类枚举

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")  # 匹配 [[目标]] / [[目标|别名]]
_RELATED_HEADING_RE = re.compile(r"^##\s*.*相关知识\s*$", re.MULTILINE)  # 匹配"## xxx相关知识"标题


# ---------- LLM 结构化输出 schema ----------

# 定义单条关系的数据模型
class RelationItem(BaseModel):
    target: str                                # 目标概念 ID
    type: Literal["依赖", "组成", "对比", "演进", "应用", "相关"]  # 关系类型（限枚举）
    description: str = ""                      # 关系描述（可空）


# 定义单篇概念文档的 LLM 抽取结果模型
class GraphExtractSchema(BaseModel):
    """单篇概念文档的 LLM 抽取结果。"""
    summary: str                               # 概念摘要
    category: Literal["基础架构", "检索增强", "Agent工程", "提示工程", "训练与优化"]  # 所属大类
    relations: list[RelationItem]              # 关系列表


# ---------- 数据模型 ----------

# 定义概念词条原始文档模型
@dataclass
class ConceptDoc:
    """概念词条原始文档（归一化前的解析结果）。"""
    file: str                                  # 源文件名
    title: str                                 # 标题
    aliases: list[str]                         # 别名列表
    tags: list[str]                            # 标签列表
    content: str                               # 正文内容


# 定义对齐后的概念节点模型
@dataclass
class Concept:
    """对齐后的概念节点。id 为 title 归一化结果，全图唯一。"""
    id: str                                    # 归一化后的概念 ID
    title: str                                 # 展示标题
    aliases: list[str]                         # 别名列表
    tags: list[str]                            # 标签列表
    file: str                                  # 源文件名
    content: str                               # 全文内容
    summary: str = ""                          # LLM 摘要（默认空）
    category: str = "基础架构"                  # 所属大类（默认基础架构）


# ---------- 纯函数层 ----------

# 定义概念名归一化函数
def normalize_concept(name: str) -> str:
    """概念名归一化：去所有空白 + 小写。title/aliases/stem/wikilink 目标统一走此函数对齐。"""
    return re.sub(r"\s+", "", name).lower()   # 去掉所有空白并转小写


# 定义单篇 md 解析函数
def parse_doc(path: Path) -> Optional[ConceptDoc]:
    """解析单篇 md。损坏（frontmatter 未闭合等）或正文过短的文件返回 None 跳过。"""
    try:                                       # 尝试加载文件
        post = frontmatter.load(path)          # 解析前置元数据与正文
    except Exception:                          # 解析失败
        logger.warning("graph_builder: 解析失败跳过 %s", path.name)  # 记录告警
        return None                            # 返回 None 跳过
    content = post.content.strip()             # 取正文并去除首尾空白
    if len(content) < MIN_BODY_CHARS:          # 正文过短视为占位/损坏
        logger.info("graph_builder: 文档过短跳过 %s（%d 字）", path.name, len(content))  # 记录
        return None                            # 返回 None 跳过
    meta = post.metadata or {}                 # 取元数据（无则空字典）
    raw_tags = meta.get("tags", [])            # 取原始 tags
    if isinstance(raw_tags, str):              # tags 是逗号分隔字符串
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]  # 拆分去空白
    else:                                      # tags 是列表
        tags = [str(t) for t in raw_tags]      # 转字符串列表
    return ConceptDoc(                         # 构造文档对象
        file=path.name,                        # 文件名
        title=str(meta.get("title") or path.stem),  # 标题（无则用 stem）
        aliases=[str(a) for a in meta.get("aliases", [])],  # 别名列表
        tags=tags,                             # 标签列表
        content=content,                       # 正文
    )


# 定义概念对齐函数
def align_concepts(docs: list[ConceptDoc]) -> tuple[dict[str, Concept], dict[str, str]]:
    """概念对齐：title 归一化为主键；同名概念（历史版本）取内容更长者。

    返回 (概念表, 别名→概念ID 映射)。aliases 与文件名 stem 也登记进别名映射，
    供 wikilink/"相关知识"条目的目标解析使用。
    """
    by_key: dict[str, Concept] = {}            # 概念表，键为归一化 ID
    for d in sorted(docs, key=lambda x: len(x.content), reverse=True):  # 按正文长度降序遍历
        cid = normalize_concept(d.title)       # 归一化标题为主键
        if not cid or cid in by_key:           # 空键或已存在同名概念
            continue  # 重复历史版本：已保留内容更长的那份
        by_key[cid] = Concept(                 # 登记概念（首个即正文最长者）
            id=cid, title=d.title, aliases=d.aliases, tags=d.tags,
            file=d.file, content=d.content,
        )
    alias_to_id: dict[str, str] = {}           # 别名→概念 ID 映射
    for c in by_key.values():                  # 遍历所有概念
        for a in c.aliases:                    # 遍历其别名
            alias_to_id.setdefault(normalize_concept(a), c.id)  # 登记一词条只取首个概念
        stem = normalize_concept(Path(c.file).stem)  # 归一化文件名 stem
        if stem:                               # 非空 stem
            alias_to_id.setdefault(stem, c.id) # 也登记进映射
    return by_key, alias_to_id                 # 返回概念表与别名映射


# 定义 wikilink 抽取函数
def extract_wikilinks(content: str) -> list[str]:
    """抽取全文 [[XXX]] / [[XXX|alias]] 的目标名（alias 形态取竖线前部分）。"""
    return _WIKILINK_RE.findall(content)       # 正则找出所有 wikilink 目标名


# 定义"相关知识"章节解析函数
def extract_related_section(content: str) -> list[tuple[str, str]]:
    """解析"相关知识"章节：返回 [(概念名, 描述)]。

    定位 `## xxx相关知识` 标题，截取到下一个二级标题或文末；
    条目形如 `- [[LLM 大语言模型]] — Agent 的"大脑"基础`。
    """
    m = _RELATED_HEADING_RE.search(content)    # 查找相关知识标题
    if not m:                                  # 无该标题
        return []                              # 返回空列表
    rest = content[m.end():]                   # 取标题之后的内容
    nxt = re.search(r"^##\s", rest, re.MULTILINE)  # 找下一个二级标题
    section = rest[: nxt.start()] if nxt else rest  # 截取章节文本
    items: list[tuple[str, str]] = []          # 存放 (概念名, 描述)
    for line in section.splitlines():          # 逐行处理
        line = line.strip()                    # 去空白
        if not line.startswith(("-", "*")):    # 非列表项
            continue                           # 跳过
        lm = _WIKILINK_RE.search(line)         # 找行内 wikilink
        if not lm:                             # 无链接则非有效条目
            continue                           # 跳过
        desc = line[lm.end():].lstrip(" —-—·").strip()  # 取链接后的描述文本
        items.append((lm.group(1), desc))      # 追加 (概念名, 描述)
    return items                               # 返回条目列表


# 定义 wikilink 目标解析函数
def resolve_target(raw: str, by_key: dict[str, Concept], alias_to_id: dict[str, str]) -> Optional[str]:
    """wikilink/条目目标 → 概念 ID。不在概念清单内返回 None（该边丢弃）。"""
    n = normalize_concept(raw)                 # 归一化目标
    if n in by_key:                            # 目标本身就是概念 ID
        return n                               # 直接返回
    return alias_to_id.get(n)                  # 否则查别名映射（查不到返回 None）


# 定义规则边目标收集函数（内部辅助）
def _collect_rule_targets(content: str) -> list[tuple[str, str]]:
    """相关知识条目（带描述）优先，其余全文 wikilink 补充；同名去重。"""
    out: list[tuple[str, str]] = []            # 结果列表
    seen: set[str] = set()                     # 去重集合
    for name, desc in extract_related_section(content):  # 先处理相关知识条目
        if name not in seen:                   # 本名未出现过
            seen.add(name)                     # 记录
            out.append((name, desc))           # 追加（带描述）
    for raw in extract_wikilinks(content):     # 补充全文 wikilink
        if raw not in seen:                    # 未出现过
            seen.add(raw)                      # 记录
            out.append((raw, ""))              # 追加（无描述）
    return out                                 # 返回目标列表


# 定义规则边构建函数
def build_rule_edges(by_key: dict[str, Concept], alias_to_id: dict[str, str]) -> list[dict]:
    """规则边：wikilink + 相关知识章节 → type 恒为"相关"。

    无序对去重、丢弃未知目标与自环；描述取"相关知识"章节的破折号文本。
    """
    edges: list[dict] = []                     # 边列表
    seen_pairs: set[tuple[str, str]] = set()   # 无序对去重集合
    for c in by_key.values():                  # 遍历每个概念
        for raw, desc in _collect_rule_targets(c.content):  # 收集其规则目标
            tid = resolve_target(raw, by_key, alias_to_id)  # 解析概念 ID
            if not tid or tid == c.id:         # 未知目标或自环
                continue                       # 丢弃
            pair = tuple(sorted((c.id, tid)))  # 规范为无序对
            if pair in seen_pairs:             # 该对已有
                continue                       # 跳过
            seen_pairs.add(pair)               # 记录该对
            edges.append({                     # 追加边
                "source": c.id, "target": tid, # 起止概念
                "type": "相关", "via": "rule", "description": desc,  # 类型/来源/描述
            })
    return edges                               # 返回规则边列表


# 定义规则边与 LLM 边合并函数
def merge_edges(rule_edges: list[dict], llm_edges: list[dict]) -> list[dict]:
    """无序对合并：规则覆盖过的对 via 保持 rule（作者确认，可靠度更高），
    type/description 采用 LLM 的细分标注；LLM 独有的边 via=llm。"""
    by_pair: dict[tuple[str, str], dict] = {}  # 按无序对索引边
    for e in rule_edges:                       # 先放入规则边
        by_pair[tuple(sorted((e["source"], e["target"])))] = dict(e)  # 键为无序对
    for e in llm_edges:                        # 再处理 LLM 边
        pair = tuple(sorted((e["source"], e["target"])))  # 计算无序对
        if pair in by_pair:                    # 该对已被规则边覆盖
            merged = by_pair[pair]             # 取已有边
            merged["type"] = e["type"]         # 采用 LLM 的细分类型
            if e.get("description"):           # LLM 有描述
                merged["description"] = e["description"]  # 覆盖描述
        else:                                  # LLM 独有边
            by_pair[pair] = {                  # 直接新增
                "source": e["source"], "target": e["target"],
                "type": e["type"], "via": "llm",  # 来源标记为 llm
                "description": e.get("description", ""),
            }
    return list(by_pair.values())              # 返回合并后的边列表


# 定义节点度数计算函数
def compute_degrees(nodes: list[dict], edges: list[dict]) -> None:
    """按合并后边数计算各节点度数（就地写入 degree 字段），前端据此定节点大小。"""
    for n in nodes:                            # 初始化所有节点度数为 0
        n["degree"] = 0
    for e in edges:                            # 遍历每条边
        for n in nodes:                        # 遍历每个节点
            if n["id"] in (e["source"], e["target"]):  # 该节点是边的端点
                n["degree"] += 1               # 度数加一


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


# 定义抽取用户 prompt 构造函数
def build_extract_user_prompt(c: Concept, concept_ids: list[str]) -> str:
    """构造抽取 prompt：概念 ID 清单 + 当前概念 + 截断后的文档内容。"""
    id_list = "、".join(concept_ids)           # 用顿号拼接概念 ID 清单
    return (                                   # 返回拼好的 prompt 文本
        f"概念 ID 清单（relations.target 只能从中选择）：{id_list}\n\n"
        f"当前概念：{c.title}（ID: {c.id}）\n\n"
        f"文档内容：\n{c.content[:_LLM_CONTENT_CAP]}"  # 截断超长内容
    )


# 定义单篇概念 LLM 抽取函数
async def extract_concept_with_llm(
    c: Concept, by_key: dict[str, Concept], alias_to_id: dict[str, str]
) -> Optional[dict]:
    """单篇 LLM 抽取。call_llm 内部已有 3 次重试，重试耗尽返回 None（该篇降级）。

    返回值经净化：非法 category 兜底、非法 type 归"相关"、清单外 target 丢弃。
    """
    ids = list(by_key.keys())                  # 取得全部概念 ID 清单
    try:                                       # 尝试调用 LLM
        result = await call_llm(               # 调用 LLM（含重试）
            _EXTRACT_SYSTEM_PROMPT,            # 系统提示词
            build_extract_user_prompt(c, ids), # 构造用户 prompt
            temperature=0.2,                   # 低温度保证确定性
            output_schema=GraphExtractSchema,  # 结构化输出 schema
            model=settings.MODEL_FLASH,        # 用 flash 模型
        )
    except Exception:                          # 调用失败（重试耗尽）
        logger.warning("graph_builder: LLM 抽取失败降级 %s", c.title, exc_info=True)  # 告警
        return None                            # 该篇降级跳过
    structured = (result or {}).get("structured") or {}  # 取结构化结果
    category = structured.get("category")      # 取大类
    if category not in CATEGORIES:             # 非法大类
        category = "基础架构"                  # 兜底为默认
    relations: list[dict] = []                 # 净化后的关系列表
    for r in structured.get("relations", []):  # 遍历 LLM 返回的关系
        tid = resolve_target(str(r.get("target", "")), by_key, alias_to_id)  # 校验目标概念
        if not tid or tid == c.id:             # 未知目标或自环
            continue                           # 丢弃
        rtype = r.get("type")                  # 取关系类型
        if rtype not in RELATION_TYPES:        # 非法类型
            rtype = "相关"                     # 归为相关
        relations.append({                     # 追加净化后的关系
            "target": tid, "type": rtype,
            "description": str(r.get("description", ""))[:30],  # 描述截断 30 字
        })
    return {                                   # 返回净化后的抽取结果
        "summary": str(structured.get("summary", ""))[:60],  # 摘要截断 60 字
        "category": category,                  # 大类
        "relations": relations,                # 关系列表
    }


# ---------- 构建入口 ----------

# 定义完整知识图谱构建函数
async def build_knowledge_graph(output_path: Optional[str] = None) -> dict:
    """完整管线：扫描 raw → 对齐 → 规则边 → LLM 抽取 → 合并 → 写 kg.json。

    供 index.py 在索引重建成功后调用；异常向上抛（调用方决定是否阻塞）。
    """
    # 跟随全局 KB_PROFILE 的知识库目录（drone / obsidian），失败由调用方兜底不阻塞索引
    profile = resolve_kb_profile()             # 解析生效 profile
    raw_dir = profile.data_dir                 # 知识库目录
    out = Path(output_path or settings.KG_JSON_PATH)  # 输出路径（未指定用配置默认）

    docs: list[ConceptDoc] = []                # 原始文档列表
    # drone 库为子目录结构，递归遍历并排除 README/sources；obsidian 保持顶层遍历
    for p in iter_kb_markdown_files(raw_dir, recursive=profile.reader == "drone"):  # 遍历 md 文件
        d = parse_doc(p)                       # 解析（损坏/过短返回 None）
        if d:                                  # 解析成功
            docs.append(d)                     # 收集文档
    by_key, alias_to_id = align_concepts(docs) # 概念对齐
    rule_edges = build_rule_edges(by_key, alias_to_id)  # 构建规则边

    llm_edges: list[dict] = []                 # LLM 边列表
    for c in by_key.values():                  # 遍历每个概念
        extracted = await extract_concept_with_llm(c, by_key, alias_to_id)  # LLM 抽取
        if not extracted:                      # 抽取失败已降级
            continue                           # 跳过该篇
        c.summary = extracted["summary"]       # 回填摘要
        c.category = extracted["category"]     # 回填大类
        for r in extracted["relations"]:       # 遍历抽取出的关系
            llm_edges.append({                 # 构造成 LLM 边
                "source": c.id, "target": r["target"],
                "type": r["type"], "via": "llm", "description": r["description"],
            })

    edges = merge_edges(rule_edges, llm_edges) # 合并两类边
    nodes = [                                  # 构造节点列表
        {
            "id": c.id, "title": c.title, "aliases": c.aliases,
            "summary": c.summary, "category": c.category,
            "tags": c.tags, "file": c.file, "degree": 0,
        }
        for c in by_key.values()               # 遍历所有概念
    ]
    compute_degrees(nodes, edges)              # 计算各节点度数

    kg = {"built_at": datetime.now().isoformat(), "nodes": nodes, "edges": edges}  # 组装图谱数据
    out.parent.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在
    out.write_text(json.dumps(kg, ensure_ascii=False, indent=2), encoding="utf-8")  # 写 kg.json
    logger.info("graph_builder: %d 节点 %d 边 → %s", len(nodes), len(edges), out)  # 记录结果
    return {"nodes": len(nodes), "edges": len(edges)}  # 返回统计