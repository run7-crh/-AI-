import pytest
from pathlib import Path
from app.rag.readers import ObsidianMarkdownReader, DroneMarkdownReader, iter_kb_markdown_files

@pytest.fixture
def reader():
    return ObsidianMarkdownReader()

def test_strip_wikilinks_simple(reader):
    text = "参考 [[Agent]] 章节"
    result = reader._strip_wikilinks(text)
    assert result == "参考 Agent 章节"

def test_strip_wikilinks_with_alias(reader):
    text = "使用 [[Agent|智能体]] 概念"
    result = reader._strip_wikilinks(text)
    assert result == "使用 智能体 概念"

def test_strip_callouts(reader):
    text = "> [!warning] 注意\n> 这是警告内容"
    result = reader._strip_callouts(text)
    assert "[!" not in result
    assert "注意" in result

def test_strip_embeds(reader):
    text = "示意图 ![[diagram.png]] 说明"
    result = reader._strip_embeds(text)
    assert "![[diagram.png]]" not in result
    assert "示意图" in result

def test_load_real_obsidian_file(reader, tmp_path):
    md = tmp_path / "test.md"
    md.write_text("""---
title: 测试笔记
tags: [AI, Agent]
---

# 测试笔记

这是 [[Agent]] 的内容。

> [!note] 提示
> 重要信息
""", encoding="utf-8")

    docs = reader.load_data(file_path=md)
    assert len(docs) >= 1
    assert docs[0].metadata["title"] == "测试笔记"
    assert "AI" in docs[0].metadata["tags"]
    assert "[[" not in docs[0].text
    assert "[!note]" not in docs[0].text


def test_document_id_is_stable_and_marks_local_source(reader, tmp_path):
    md = tmp_path / "stable.md"
    md.write_text("# 标题\n\n内容", encoding="utf-8")
    first = reader.load_data(file_path=md)[0]
    second = reader.load_data(file_path=md)[0]
    assert first.id_ == second.id_
    assert first.metadata["document_id"] == first.id_
    assert first.metadata["source_type"] == "local"


# ---------------------------------------------------------------------------
# 阶段 1：drone 知识库读取器与文件遍历
# ---------------------------------------------------------------------------

DRONE_DOC = """---
document_id: drone_troubleshooting_compass
document_type: troubleshooting
product_model: mini_4_pro
component: compass
fault_type: compass_abnormal
source_type: official
data_type: factual
source_id: ["SOURCE-008", "SOURCE-007"]
version: "1.0"
---

# 故障：指南针（罗盘）干扰 / 需校准

## 排查步骤（官方）

1. 远离磁场或大型金属后重新校准。
"""


def test_drone_reader_promotes_identity_fields(tmp_path):
    md = tmp_path / "drone_troubleshooting_compass.md"
    md.write_text(DRONE_DOC, encoding="utf-8")
    docs = DroneMarkdownReader().load_data(file_path=md)
    meta = docs[0].metadata
    assert meta["document_id"] == "drone_troubleshooting_compass"
    assert meta["document_type"] == "troubleshooting"
    assert meta["product_model"] == "mini_4_pro"
    assert meta["component"] == "compass"
    assert meta["fault_type"] == "compass_abnormal"
    assert meta["data_type"] == "factual"
    assert meta["source_type"] == "official"
    assert meta["version"] == "1.0"
    assert meta["source_id"] == "SOURCE-008,SOURCE-007"  # 列表展平为逗号字符串


def test_drone_reader_title_falls_back_to_first_h1(tmp_path):
    md = tmp_path / "drone_troubleshooting_compass.md"
    md.write_text(DRONE_DOC, encoding="utf-8")
    docs = DroneMarkdownReader().load_data(file_path=md)
    # 无 title frontmatter，用正文首个一级标题替代文件名 stem
    assert docs[0].metadata["title"] == "故障：指南针（罗盘）干扰 / 需校准"


def test_drone_reader_document_id_becomes_node_identity(tmp_path):
    md = tmp_path / "drone_troubleshooting_compass.md"
    md.write_text(DRONE_DOC, encoding="utf-8")
    reader = DroneMarkdownReader()
    first = reader.load_data(file_path=md)[0]
    second = reader.load_data(file_path=md)[0]
    # Document.id_ 同步为知识库身份 id（落库 ref_doc_id / chunk id 前缀均用它），重建稳定
    assert first.id_ == second.id_
    assert first.id_ == "drone_troubleshooting_compass"
    assert first.metadata["document_id"] == "drone_troubleshooting_compass"


def test_drone_reader_falls_back_to_hash_without_frontmatter_id(tmp_path):
    md = tmp_path / "no_id.md"
    md.write_text("---\ndocument_type: sop\n---\n\n# 无身份文档\n\n内容。", encoding="utf-8")
    doc = DroneMarkdownReader().load_data(file_path=md)[0]
    # frontmatter 缺 document_id 时保持基类哈希行为
    assert doc.metadata["document_id"] == doc.id_
    assert len(doc.id_) == 64


def test_iter_kb_markdown_files_recursive_excludes_helpers(tmp_path):
    (tmp_path / "products").mkdir()
    (tmp_path / "sop").mkdir()
    (tmp_path / "sources").mkdir()
    (tmp_path / "products" / "a.md").write_text("x", encoding="utf-8")
    (tmp_path / "sop" / "b.md").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "sources" / "sources.md").write_text("x", encoding="utf-8")

    recursive = iter_kb_markdown_files(tmp_path, recursive=True)
    names = {p.relative_to(tmp_path).as_posix() for p in recursive}
    assert names == {"products/a.md", "sop/b.md"}  # 排除 README 与 sources 登记表

    # 顶层遍历保持原 glob 行为：不过滤、仅顶层（README.md 在顶层会被返回）
    top = iter_kb_markdown_files(tmp_path, recursive=False)
    assert {p.name for p in top} == {"README.md"}
