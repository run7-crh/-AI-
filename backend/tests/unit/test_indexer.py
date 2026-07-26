import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.rag.indexer import Indexer

@pytest.fixture
def temp_dirs():
    # persist_dir 用 ignore_cleanup_errors=True：chromadb 在 Windows 上会持有
    # chroma.sqlite3 文件锁，TemporaryDirectory 默认清理会抛 PermissionError
    with tempfile.TemporaryDirectory() as data_dir, \
         tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as persist_dir:
        (Path(data_dir) / "test.md").write_text("# 测试\n\n这是测试内容", encoding="utf-8")
        yield data_dir, persist_dir

def test_indexer_init_creates_chroma_collection(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"):
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
    assert idx.chroma_collection is not None
    assert idx.data_dir == Path(data_dir)
    assert idx.persist_dir == Path(persist_dir)

def test_indexer_build_loads_documents(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        idx.build()
        mock_vsi.from_documents.assert_called_once()
        docs = mock_vsi.from_documents.call_args.args[0]
        assert len(docs) >= 1

def test_indexer_get_retriever_returns_rag_retriever(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"):
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        idx.index = MagicMock()
        r = idx.get_retriever()
        from app.rag.retriever import RAGRetriever
        assert isinstance(r, RAGRetriever)
