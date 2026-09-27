"""Validation for temporary attachment payloads.

This module does not extract document text or scan for malware.  It rejects
obviously unsafe inputs before storage and exposes a scan status for the later
scanner integration.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePath


ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx", ".log", ".json", ".csv", ".jpg", ".jpeg", ".png", ".webp"}
# 图片附件走 VLM 观察管线（vision_service），与文本抽取管线分流；是否放行由
# AttachmentStore 的 VISION 开关裁决，本模块只负责"给了图片就严格校验"。
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILENAME_LENGTH = 180
MAX_ZIP_ENTRIES = 1000
MAX_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 1000

_MIME_ALIASES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".log": {"text/plain"},
    ".json": {"application/json", "text/json"},
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
}


class AttachmentValidationError(ValueError):
    """Safe, machine-readable validation failure."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class ValidatedAttachment:
    original_name: str
    extension: str
    declared_mime: str | None
    detected_mime: str
    size_bytes: int
    sha256: str


def validate_filename(filename: str, *, max_length: int = MAX_FILENAME_LENGTH) -> ValidatedAttachment:
    if not isinstance(filename, str) or not filename:
        raise AttachmentValidationError("filename_invalid")
    if len(filename) > max_length:
        raise AttachmentValidationError("filename_too_long")
    if any(ord(char) < 32 or ord(char) == 127 for char in filename):
        raise AttachmentValidationError("filename_control_character")
    if "\x00" in filename or "/" in filename or "\\" in filename:
        raise AttachmentValidationError("filename_path_traversal")
    if filename in {".", ".."} or filename.startswith("."):
        raise AttachmentValidationError("filename_invalid")
    suffixes = PurePath(filename).suffixes
    if len(suffixes) != 1:
        raise AttachmentValidationError("double_extension")
    extension = suffixes[0].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise AttachmentValidationError("extension_not_allowed")
    return ValidatedAttachment(filename, extension, None, "", 0, "")


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = payload.decode(encoding)
            if "\x00" in text:
                raise AttachmentValidationError("binary_text_payload")
            return text
        except UnicodeDecodeError:
            continue
    raise AttachmentValidationError("text_encoding_invalid")


def _validate_json(payload: bytes) -> None:
    try:
        value = json.loads(_decode_text(payload))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttachmentValidationError("json_invalid") from exc

    def depth(item: object, current: int = 0) -> int:
        if current > 20:
            return current
        if isinstance(item, dict):
            return max((depth(v, current + 1) for v in item.values()), default=current)
        if isinstance(item, list):
            return max((depth(v, current + 1) for v in item), default=current)
        return current

    if depth(value) > 20:
        raise AttachmentValidationError("json_too_deep")


def _validate_docx(payload: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise AttachmentValidationError("zip_too_many_entries")
            total = sum(info.file_size for info in infos)
            if total > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise AttachmentValidationError("zip_uncompressed_too_large")
            for info in infos:
                if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_COMPRESSION_RATIO:
                    raise AttachmentValidationError("zip_compression_ratio")
                if info.filename.startswith(("/", "\\")) or ".." in PurePath(info.filename).parts:
                    raise AttachmentValidationError("zip_path_traversal")
                # Reject Unix symlinks embedded in the archive.
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise AttachmentValidationError("zip_symlink")
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or not any(name.startswith("word/") for name in names):
                raise AttachmentValidationError("docx_signature_invalid")
            if "word/vbaProject.bin" in names:
                raise AttachmentValidationError("docx_macros_not_allowed")
    except AttachmentValidationError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise AttachmentValidationError("docx_signature_invalid") from exc


def _detect_and_validate_format(extension: str, payload: bytes) -> str:
    if extension == ".pdf":
        if not payload.startswith(b"%PDF-") or b"%%EOF" not in payload[-1024:]:
            raise AttachmentValidationError("signature_invalid")
        return "application/pdf"
    if extension in {".jpg", ".jpeg"}:
        # JPEG 以 SOI 标记开头；只校验文件头，不做深度解码（避免解码炸弹）。
        if not payload.startswith(b"\xff\xd8\xff"):
            raise AttachmentValidationError("signature_invalid")
        return "image/jpeg"
    if extension == ".png":
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AttachmentValidationError("signature_invalid")
        return "image/png"
    if extension == ".webp":
        if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
            raise AttachmentValidationError("signature_invalid")
        return "image/webp"
    if extension == ".docx":
        if not payload.startswith(b"PK"):
            raise AttachmentValidationError("signature_invalid")
        _validate_docx(payload)
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if extension == ".json":
        _validate_json(payload)
        return "application/json"
    if extension == ".csv":
        text = _decode_text(payload)
        try:
            list(csv.reader(io.StringIO(text)))
        except csv.Error as exc:
            raise AttachmentValidationError("csv_invalid") from exc
        return "text/csv"
    _decode_text(payload)
    return "text/markdown" if extension == ".md" else "text/plain"


def validate_attachment_bytes(
    filename: str,
    payload: bytes,
    declared_mime: str | None,
    *,
    max_file_bytes: int = 25 * 1024 * 1024,
    max_filename_length: int = MAX_FILENAME_LENGTH,
) -> ValidatedAttachment:
    name = validate_filename(filename, max_length=max_filename_length)
    if not isinstance(payload, (bytes, bytearray)):
        raise AttachmentValidationError("payload_invalid")
    size = len(payload)
    if size > max_file_bytes:
        raise AttachmentValidationError("file_too_large")
    if declared_mime:
        normalized = declared_mime.split(";", 1)[0].strip().lower()
        if normalized not in _MIME_ALIASES[name.extension]:
            raise AttachmentValidationError("mime_mismatch")
    detected = _detect_and_validate_format(name.extension, bytes(payload))
    return ValidatedAttachment(
        original_name=name.original_name,
        extension=name.extension,
        declared_mime=declared_mime,
        detected_mime=detected,
        size_bytes=size,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
