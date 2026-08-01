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
    # P2-2: mock configure_embedding 避免触发真实模型加载
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"):
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
    assert idx.chroma_collection is not None
    assert idx.data_dir == Path(data_dir)
    assert idx.persist_dir == Path(persist_dir)

def test_indexer_build_loads_documents(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        idx.build()
        mock_vsi.from_documents.assert_called_once()
        docs = mock_vsi.from_documents.call_args.args[0]
        assert len(docs) >= 1

def test_indexer_get_retriever_returns_rag_retriever(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"):
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        idx.index = MagicMock()
        r = idx.get_retriever()
        from app.rag.retriever import RAGRetriever
        assert isinstance(r, RAGRetriever)

def test_indexer_load_or_build_triggers_rebuild_when_collection_empty(temp_dirs):
    """空 collection 应触发 rebuild，而非静默加载空索引。"""
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        # collection 刚创建，count=0
        assert idx.chroma_collection.count() == 0
        idx.load_or_build()
        # 应该调用 build（from_documents），而非 from_vector_store
        mock_vsi.from_documents.assert_called_once()
        mock_vsi.from_vector_store.assert_not_called()

def test_indexer_load_or_build_loads_when_collection_has_docs(temp_dirs):
    """非空 collection 应直接加载，不 rebuild。"""
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        # 模拟 collection 已有文档
        idx.chroma_collection = MagicMock()
        idx.chroma_collection.count.return_value = 10
        idx.vector_store = MagicMock()
        idx.storage_context = MagicMock()
        idx.load_or_build()
        # 应该调用 from_vector_store，而非 from_documents
        mock_vsi.from_vector_store.assert_called_once()
        mock_vsi.from_documents.assert_not_called()
