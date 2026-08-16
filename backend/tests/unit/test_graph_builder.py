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
