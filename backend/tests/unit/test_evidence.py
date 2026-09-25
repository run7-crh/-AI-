from app.models.evidence import format_evidence_context


def test_format_evidence_context_keeps_titles_and_urls():
    context = format_evidence_context([
        {
            "source_type": "web",
            "title": "官方文档",
            "url": "https://example.com/docs",
            "content": "正文",
        }
    ])
    assert "官方文档" in context
    assert "https://example.com/docs" in context
    assert "正文" in context


def test_format_evidence_context_skips_provider_error_items():
    context = format_evidence_context([
        {"is_error": True, "title": "联网搜索失败", "content": "secret error"}
    ])
    assert context == "（无可用来源）"


def test_format_evidence_context_preserves_trace_metadata_and_synthetic_label():
    context = format_evidence_context([{
        "source_type": "local", "source": "case.md", "title": "案例",
        "document_id": "doc-1", "source_id": "SOURCE-8",
        "product_model": "mini_4_pro", "data_type": "synthetic", "content": "案例正文",
    }])
    assert "document_id=doc-1" in context
    assert "source_id=SOURCE-8" in context
    assert "product_model=mini_4_pro" in context
    assert "（模拟案例）" in context
