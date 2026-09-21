import pytest

from app.services.knowledge_base_import import ImportValidationError, KnowledgeBaseImportService


def test_import_rejects_path_traversal_and_non_markdown(tmp_path):
    service = KnowledgeBaseImportService(tmp_path, max_file_bytes=100, max_files=2)
    with pytest.raises(ImportValidationError, match="markdown_only"):
        service.validate("notes.txt", b"x")
    with pytest.raises(ImportValidationError, match="unsafe_filename"):
        service.validate("..\\outside.md", b"# x")


def test_import_writes_files_atomically(tmp_path):
    service = KnowledgeBaseImportService(tmp_path, max_file_bytes=100, max_files=2)
    result = service.import_files([("guide.md", b"# guide")])
    assert result == ["guide.md"]
    assert (tmp_path / "guide.md").read_bytes() == b"# guide"


def test_import_rejects_duplicate_names_and_limits(tmp_path):
    service = KnowledgeBaseImportService(tmp_path, max_file_bytes=3, max_files=1)
    with pytest.raises(ImportValidationError, match="file_too_large"):
        service.import_files([("a.md", b"abcd")])
    with pytest.raises(ImportValidationError, match="duplicate_filename"):
        service.import_files([("a.md", b"a"), ("a.md", b"b")])


def test_import_rejects_case_insensitive_duplicate_names(tmp_path):
    service = KnowledgeBaseImportService(tmp_path, max_file_bytes=100, max_files=3)
    with pytest.raises(ImportValidationError, match="duplicate_filename"):
        service.import_files([("A.md", b"a"), ("a.md", b"b")])
