"""Bounded, non-executing text extraction for temporary attachments."""

from __future__ import annotations

import csv
import io
import json
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from app.models.attachment import Attachment
from app.services.attachment_security import (
    AttachmentValidationError,
    _decode_text,
    _validate_docx,
)


@dataclass(frozen=True)
class AttachmentExtractionLimits:
    max_chars: int = 200_000
    max_line_chars: int = 10_000
    max_pdf_pages: int = 100
    max_parse_seconds: float = 10.0
    max_json_depth: int = 20
    max_json_array_items: int = 10_000
    max_json_string_chars: int = 50_000
    max_json_total_chars: int = 200_000
    max_csv_rows: int = 10_000
    max_csv_columns: int = 200
    max_csv_cell_chars: int = 20_000


@dataclass(frozen=True)
class ExtractionResult:
    extraction_status: str
    extracted_chars: int
    sanitized_text: str | None
    extraction_error_code: str | None
    extraction_summary: str


class DefaultAttachmentExtractor:
    """Extract only text, with deterministic limits and safe error reporting."""

    def __init__(self, *, limits: AttachmentExtractionLimits | None = None):
        self.limits = limits or AttachmentExtractionLimits()

    def extract(self, attachment: Attachment, payload: bytes) -> ExtractionResult:
        started = time.monotonic()
        try:
            if not isinstance(payload, (bytes, bytearray)):
                raise AttachmentValidationError("payload_invalid")
            extension = attachment.extension.lower()
            if extension in {".txt", ".md", ".log"}:
                text = self._text(bytes(payload))
            elif extension == ".json":
                text = self._json(bytes(payload))
            elif extension == ".csv":
                text = self._csv(bytes(payload))
            elif extension == ".docx":
                text = self._docx(bytes(payload))
            elif extension == ".pdf":
                text = self._pdf(bytes(payload), started)
            else:
                raise AttachmentValidationError("extension_not_allowed")
            text = self._finish(text)
            return ExtractionResult("ready", len(text), text, None, "untrusted_attachment_text")
        except AttachmentValidationError as exc:
            return ExtractionResult("skipped" if exc.code == "no_extractable_text" else "failed", 0, None, exc.code, self._summary(exc.code))
        except Exception:
            # Do not expose paths, payloads, parser messages, or stack traces.
            return ExtractionResult("failed", 0, None, "extraction_failed", "附件文本抽取失败")

    def _check_time(self, started: float) -> None:
        if time.monotonic() - started > self.limits.max_parse_seconds:
            raise AttachmentValidationError("extraction_timeout")

    def _finish(self, text: str) -> str:
        text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
        if len(text) > self.limits.max_chars:
            raise AttachmentValidationError("extraction_too_large")
        if any(len(line) > self.limits.max_line_chars for line in text.split("\n")):
            raise AttachmentValidationError("text_line_too_long")
        return text

    def _text(self, payload: bytes) -> str:
        return _decode_text(payload)

    def _json(self, payload: bytes) -> str:
        def reject_constant(_: str) -> None:
            raise ValueError

        try:
            value = json.loads(_decode_text(payload), parse_constant=reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise AttachmentValidationError("json_invalid")

        def sanitize(item: Any, depth: int = 0) -> Any:
            if depth > self.limits.max_json_depth:
                raise AttachmentValidationError("json_too_deep")
            if isinstance(item, dict):
                result = {}
                for key, child in item.items():
                    normalized_key = "".join(char for char in str(key).lower() if char.isalnum())
                    if any(token in normalized_key for token in ("password", "passwd", "token", "apikey", "secret", "authorization", "privatekey")):
                        result[key] = "[REDACTED]"
                    else:
                        result[key] = sanitize(child, depth + 1)
                return result
            if isinstance(item, list):
                if len(item) > self.limits.max_json_array_items:
                    raise AttachmentValidationError("json_array_limit")
                return [sanitize(child, depth + 1) for child in item]
            if isinstance(item, str) and len(item) > self.limits.max_json_string_chars:
                raise AttachmentValidationError("json_string_limit")
            return item

        text = json.dumps(sanitize(value), ensure_ascii=False, indent=2, sort_keys=True)
        if len(text) > self.limits.max_json_total_chars:
            raise AttachmentValidationError("json_size_limit")
        return text

    def _csv(self, payload: bytes) -> str:
        text = _decode_text(payload)
        try:
            reader = csv.reader(io.StringIO(text, newline=""))
            rows = []
            for row_number, row in enumerate(reader, start=1):
                if row_number > self.limits.max_csv_rows:
                    raise AttachmentValidationError("csv_row_limit")
                if len(row) > self.limits.max_csv_columns:
                    raise AttachmentValidationError("csv_column_limit")
                if any(len(cell) > self.limits.max_csv_cell_chars for cell in row):
                    raise AttachmentValidationError("csv_cell_too_long")
                rows.append(row)
            output = io.StringIO(newline="")
            csv.writer(output, lineterminator="\n").writerows(rows)
            return output.getvalue()
        except csv.Error:
            raise AttachmentValidationError("csv_invalid")

    def _docx(self, payload: bytes) -> str:
        _validate_docx(payload)
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = set(archive.namelist())
                if any(name.startswith(("word/embeddings/", "word/embeddings", "word/activeX/", "word/externalLinks/")) for name in names):
                    raise AttachmentValidationError("docx_embedded_object")
                root = ElementTree.fromstring(archive.read("word/document.xml"))
        except AttachmentValidationError:
            raise
        except (KeyError, ElementTree.ParseError, zipfile.BadZipFile):
            raise AttachmentValidationError("docx_invalid")
        lines = []
        for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            value = "".join(node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
            if value:
                lines.append(value)
        return "\n".join(lines)

    def _pdf(self, payload: bytes, started: float) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise AttachmentValidationError("pdf_dependency_missing")
        try:
            reader = PdfReader(io.BytesIO(payload), strict=False)
            if reader.is_encrypted:
                raise AttachmentValidationError("pdf_encrypted")
            if len(reader.pages) > self.limits.max_pdf_pages:
                raise AttachmentValidationError("pdf_page_limit_exceeded")
            pages = []
            for page in reader.pages:
                self._check_time(started)
                pages.append(page.extract_text() or "")
            text = "\n".join(pages)
            if not text.strip():
                raise AttachmentValidationError("no_extractable_text")
            return text
        except AttachmentValidationError:
            raise
        except Exception:
            raise AttachmentValidationError("pdf_invalid")

    @staticmethod
    def _summary(code: str) -> str:
        summaries = {
            "no_extractable_text": "PDF 中没有可提取文本，暂不执行 OCR",
            "pdf_dependency_missing": "PDF 解析依赖不可用",
            "pdf_encrypted": "PDF 已加密，无法安全抽取",
        }
        return summaries.get(code, "附件文本抽取未完成")
