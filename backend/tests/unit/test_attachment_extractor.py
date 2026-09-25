import io
import json
import zipfile

from app.models.attachment import Attachment
from app.services.attachment_extractor import AttachmentExtractionLimits, DefaultAttachmentExtractor


def attachment(name: str) -> Attachment:
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    return Attachment("att_test", "conv", name, "." + name.rsplit('.', 1)[-1], None, None, 0, "", "ready", "pending", "not_run", "att_test/payload.bin", now, now + timedelta(hours=1))


def extract(name, payload, limits=None):
    return DefaultAttachmentExtractor(limits=limits).extract(attachment(name), payload)


def test_text_formats_and_normalized_newlines():
    for name in ("a.txt", "a.md", "a.log"):
        result = extract(name, "第一行\r\n第二行".encode("utf-8"))
        assert result.extraction_status == "ready"
        assert result.sanitized_text == "第一行\n第二行"
        assert result.extracted_chars == 7


def test_utf16_and_empty_file():
    assert extract("a.txt", "hello".encode("utf-16")).sanitized_text == "hello"
    result = extract("a.txt", b"")
    assert result.extraction_status == "ready" and result.extracted_chars == 0


def test_json_redacts_sensitive_values_and_serializes_stably():
    result = extract("a.json", json.dumps({"token": "secret", "ok": 1}).encode())
    assert "secret" not in result.sanitized_text
    assert "[REDACTED]" in result.sanitized_text
    assert result.extraction_status == "ready"


def test_json_depth_and_invalid_payload():
    deep = 0
    for _ in range(22):
        deep = {"x": deep}
    result = extract("a.json", json.dumps(deep).encode())
    assert result.extraction_status == "failed" and result.extraction_error_code == "json_too_deep"
    result = extract("a.json", b"{")
    assert result.extraction_error_code == "json_invalid"


def test_csv_limits_and_formula_is_plain_text():
    result = extract("a.csv", b"name,value\n=SUM(A1),2\n")
    assert result.extraction_status == "ready"
    assert "=SUM(A1)" in result.sanitized_text
    limited = extract("a.csv", b"a,b\n1,2\n", AttachmentExtractionLimits(max_csv_rows=1))
    assert limited.extraction_error_code == "csv_row_limit"


def test_docx_extracts_paragraphs_and_tables_without_objects():
    xml = b'''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'''
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    result = extract("a.docx", out.getvalue())
    assert result.extraction_status == "ready"
    assert "Hello" in result.sanitized_text and "Cell" in result.sanitized_text


def test_failures_do_not_leak_payload_or_path():
    result = extract("secret.txt", b"\xff\xfe\xff")
    assert result.extraction_status == "failed"
    assert "secret.txt" not in (result.extraction_summary or "")
    assert "\\xff" not in (result.extraction_summary or "")


def test_limits_are_enforced():
    result = extract("a.txt", b"12345", AttachmentExtractionLimits(max_chars=3))
    assert result.extraction_error_code == "extraction_too_large"
