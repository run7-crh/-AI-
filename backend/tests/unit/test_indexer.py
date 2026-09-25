import pytest
import tempfile
import json
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.rag.indexer import Indexer, create_profiled_indexer
from llama_index.core import Settings
from llama_index.core.embeddings import MockEmbedding

@pytest.fixture
def temp_dirs():
    # persist_dir 用 ignore_cleanup_errors=True：chromadb 在 Windows 上会持有
    # chroma.sqlite3 文件锁，TemporaryDirectory 默认清理会抛 PermissionError
    with tempfile.TemporaryDirectory() as data_dir, \
         tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as persist_dir:
        (Path(data_dir) / "test.md").write_text(
            "# 测试\n\n" + "这是测试内容。" * 80,
            encoding="utf-8",
        )
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


def test_indexer_skips_short_docs_and_keeps_longest_duplicate_title(temp_dirs):
    data_dir, persist_dir = temp_dirs
    (Path(data_dir) / "RAG旧版.md").write_text(
        "---\ntitle: RAG\n---\n" + "旧内容。" * 40,
        encoding="utf-8",
    )
    (Path(data_dir) / "RAG新版.md").write_text(
        "---\ntitle: R A G\n---\n" + "新内容。" * 100,
        encoding="utf-8",
    )
    (Path(data_dir) / "损坏占位.md").write_text("# 占位\n太短", encoding="utf-8")
    with patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir, persist_dir)
        idx.build()
        docs = mock_vsi.from_documents.call_args.args[0]

    titles = [doc.metadata["title"] for doc in docs]
    assert titles.count("R A G") == 1
    assert "损坏占位" not in titles


def test_indexer_build_rejects_empty_corpus_before_clearing(temp_dirs):
    data_dir, persist_dir = temp_dirs
    for path in Path(data_dir).glob("*.md"):
        path.unlink()
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        with pytest.raises(ValueError, match="知识库为空"):
            idx.build()
        mock_vsi.from_documents.assert_not_called()


def test_rebuild_failure_keeps_active_vectors_and_index(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir, persist_dir)
        active = idx.chroma_collection
        active.add(ids=["old"], documents=["old content"], embeddings=[[1.0, 0.0]])
        previous_index = object()
        idx.index = previous_index
        mock_vsi.from_documents.side_effect = RuntimeError("embedding failed")
        with pytest.raises(RuntimeError, match="embedding failed"):
            idx.build()

    assert active.get(include=[])["ids"] == ["old"]
    assert idx.chroma_collection is active
    assert idx.index is previous_index


def test_repeated_build_publishes_stable_chunks_and_preserves_old_reader(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.configure_embedding"):
        Settings.embed_model = MockEmbedding(embed_dim=8)
        idx = Indexer(data_dir, persist_dir)
        idx.build()
        previous_collection = idx.chroma_collection
        previous_ids = previous_collection.get(include=[])["ids"]
        idx.build()
        assert idx.chroma_collection.name != previous_collection.name
        assert idx.chroma_collection.get(include=[])["ids"] == previous_ids
        assert previous_collection.get(include=[])["ids"] == previous_ids

        reloaded = Indexer(data_dir, persist_dir)
        assert reloaded.chroma_collection.name == idx.chroma_collection.name


def test_rebuild_does_not_mutate_active_collection_before_build_succeeds(temp_dirs):
    """A failed rebuild leaves the active collection untouched."""
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        active = idx.chroma_collection
        mock_vsi.from_documents.side_effect = RuntimeError("build failed")
        with pytest.raises(RuntimeError, match="build failed"):
            idx.build()

    assert active.count() == 0
    assert idx.chroma_collection is active
    mock_vsi.from_documents.assert_called_once()

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


def test_indexer_load_or_build_migrates_legacy_uuid_collection(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        idx.chroma_collection = MagicMock()
        idx.chroma_collection.count.return_value = 2
        idx.chroma_collection.get.return_value = {"ids": ["uuid-1", "uuid-2"]}
        idx.load_or_build()
        mock_vsi.from_documents.assert_called_once()
        mock_vsi.from_vector_store.assert_not_called()


def test_indexer_rebuilds_when_manifest_policy_is_stale(temp_dirs):
    data_dir, persist_dir = temp_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir)
        idx.chroma_collection = MagicMock()
        idx.chroma_collection.count.return_value = 2
        idx.vector_store = MagicMock()
        idx.storage_context = MagicMock()
        idx.manifest_path.write_text(json.dumps({
            "schema_version": 1,
            "collection_name": "obsidian_kb__v_old",
            "embedding_model": "old-model",
            "chunk_size": 128,
            "chunk_overlap": 10,
        }), encoding="utf-8")
        idx._active_manifest = json.loads(idx.manifest_path.read_text(encoding="utf-8"))
        idx.load_or_build()
        mock_vsi.from_documents.assert_called_once()
        mock_vsi.from_vector_store.assert_not_called()


# ---------------------------------------------------------------------------
# 阶段 1：drone 知识库索引（递归遍历 / 排除清单 / document_id 去重 / manifest 对账）
# ---------------------------------------------------------------------------

DRONE_FM = (
    "---\n"
    "document_id: {doc_id}\n"
    "document_type: {doc_type}\n"
    "product_model: mini_4_pro\n"
    "component: compass\n"
    "data_type: factual\n"
    'source_id: ["SOURCE-008"]\n'
    "---\n\n"
)


def _make_drone_kb(data_dir: Path) -> None:
    """构造 drone 知识库最小结构：2 篇子目录文档 + README + sources + manifest。"""
    (data_dir / "products").mkdir(parents=True, exist_ok=True)
    (data_dir / "sop").mkdir(exist_ok=True)
    (data_dir / "sources").mkdir(exist_ok=True)
    (data_dir / "products" / "drone_product_a.md").write_text(
        DRONE_FM.format(doc_id="drone_product_a", doc_type="product")
        + "# 产品A\n\n" + "产品内容。" * 80,
        encoding="utf-8",
    )
    (data_dir / "sop" / "drone_sop_b.md").write_text(
        DRONE_FM.format(doc_id="drone_sop_b", doc_type="sop")
        + "# SOP B\n\n" + "步骤内容。" * 80,
        encoding="utf-8",
    )
    (data_dir / "README.md").write_text("# 知识库说明\n\n" + "说明内容。" * 100, encoding="utf-8")
    (data_dir / "sources" / "sources.md").write_text("# 来源登记\n\n" + "来源内容。" * 100, encoding="utf-8")
    (data_dir / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "document_count": 2,
        "documents": [{"document_id": "drone_product_a"}, {"document_id": "drone_sop_b"}],
    }, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def drone_dirs():
    with tempfile.TemporaryDirectory() as data_dir, \
         tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as persist_dir:
        _make_drone_kb(Path(data_dir))
        yield data_dir, persist_dir


def test_drone_recursive_indexing_excludes_helpers(drone_dirs):
    data_dir, persist_dir = drone_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir,
                      collection_name="drone_kb", reader="drone")
        idx.build()
        docs = mock_vsi.from_documents.call_args.args[0]

    names = {doc.metadata["file_name"] for doc in docs}
    assert names == {"drone_product_a.md", "drone_sop_b.md"}  # 子目录入库，README/sources 排除
    assert idx.collection_name == "drone_kb"
    assert idx.manifest_path.name == "drone_kb.active.json"   # 独立 collection 指针
    assert idx.reader_kind == "drone"


def test_drone_dedup_uses_document_id(drone_dirs):
    data_dir, persist_dir = drone_dirs
    data_dir = Path(data_dir)
    # 脏数据：两个文件共享同一 document_id，只保留正文更长的一份
    (data_dir / "sop" / "drone_dup.md").write_text(
        "---\ndocument_id: drone_product_a\ndocument_type: sop\n---\n# 重复\n\n" + "重复内容。" * 200,
        encoding="utf-8",
    )
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex") as mock_vsi:
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir,
                      collection_name="drone_kb", reader="drone")
        idx.build()
        docs = mock_vsi.from_documents.call_args.args[0]

    same_id = [doc for doc in docs if doc.metadata["document_id"] == "drone_product_a"]
    assert len(same_id) == 1
    assert same_id[0].metadata["file_name"] == "drone_dup.md"  # 更长者保留


def test_drone_manifest_reconciliation_warns_on_drift(drone_dirs, caplog):
    data_dir, persist_dir = drone_dirs
    manifest = {
        "document_count": 2,
        "documents": [{"document_id": "drone_product_a"}, {"document_id": "drone_missing"}],
    }
    (Path(data_dir) / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex"):
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir,
                      collection_name="drone_kb", reader="drone")
        with caplog.at_level(logging.WARNING, logger="app.rag.indexer"):
            idx.build()  # 漂移只告警，不抛错

    assert any("登记但未入库" in r.message for r in caplog.records)      # drone_missing
    assert any("入库但未登记" in r.message for r in caplog.records)      # drone_sop_b


def test_drone_manifest_reconciliation_passes_when_consistent(drone_dirs, caplog):
    data_dir, persist_dir = drone_dirs
    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"), \
         patch("app.rag.indexer.VectorStoreIndex"):
        idx = Indexer(data_dir=data_dir, persist_dir=persist_dir,
                      collection_name="drone_kb", reader="drone")
        with caplog.at_level(logging.WARNING, logger="app.rag.indexer"):
            idx.build()

    assert not any("manifest 对账" in r.message for r in caplog.records)  # 无漂移告警


def test_create_profiled_indexer_resolves_drone_profile(monkeypatch, drone_dirs):
    data_dir, persist_dir = drone_dirs
    import app.config as config
    monkeypatch.setattr(config.settings, "KB_PROFILE", "drone")
    monkeypatch.setattr(config.settings, "DRONE_KB_DATA_DIR", data_dir)
    monkeypatch.setattr(config.settings, "DRONE_CHROMA_COLLECTION_NAME", "drone_kb")
    monkeypatch.delenv("KB_DATA_DIR", raising=False)
    fields = set(config.settings.model_fields_set)   # 全局实例导入时快照；剔除 KB_DATA_DIR
    fields.discard("KB_DATA_DIR")
    monkeypatch.setattr(config.settings, "__pydantic_fields_set__", fields)

    with patch("app.rag.indexer.Settings"), \
         patch("app.rag.indexer.configure_embedding"):
        idx = create_profiled_indexer(persist_dir=persist_dir)

    assert idx.reader_kind == "drone"
    assert idx.data_dir == Path(data_dir)
    assert idx.collection_name == "drone_kb"
