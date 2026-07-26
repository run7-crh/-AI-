import pytest
from pathlib import Path
from app.rag.readers import ObsidianMarkdownReader

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
