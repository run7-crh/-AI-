import pytest
from unittest.mock import MagicMock, patch
from llama_index.core.schema import NodeWithScore, TextNode
from app.rag.retriever import RAGRetriever

def test_retrieve_returns_top_k_formatted():
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [
        NodeWithScore(node=TextNode(text="内容1", metadata={"file_name": "a.md", "title": "A"}), score=0.9),
        NodeWithScore(node=TextNode(text="内容2", metadata={"file_name": "b.md", "title": "B"}), score=0.8),
        NodeWithScore(node=TextNode(text="内容3", metadata={"file_name": "c.md", "title": "C"}), score=0.7),
    ]
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=3)
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str=None: nodes):
            result = r.retrieve("测试 query")
    assert len(result) == 3
    assert result[0]["content"] == "内容1"
    assert result[0]["source"] == "a.md"
    assert result[0]["title"] == "A"
    assert result[0]["score"] == 0.9

def test_retrieve_initial_recall_is_3x():
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = []
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever) as mock_cls:
        r = RAGRetriever(mock_index, top_k=3)
        r.retrieve("test")
    assert mock_cls.call_args.kwargs["similarity_top_k"] == 9


def test_retrieve_request_top_k_updates_candidate_pool_and_output_limit():
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [
        NodeWithScore(node=TextNode(text=f"内容{i}", metadata={"file_name": "a.md"}), score=1 - i * .1)
        for i in range(6)
    ]
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=3)
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str=None: nodes):
            result = r.retrieve("test", top_k=1)
    assert mock_retriever.similarity_top_k == 3
    mock_retriever.retrieve.assert_called_once_with("test")
    assert len(result) == 1
    assert result[0]["source_type"] == "local"
    assert result[0]["chunk_id"]


def test_retrieve_deduplicates_legacy_duplicate_chunks():
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [
        NodeWithScore(node=TextNode(text="重复", metadata={"file_name": "a.md"}), score=0.9),
        NodeWithScore(node=TextNode(text="重复", metadata={"file_name": "a.md"}), score=0.8),
        NodeWithScore(node=TextNode(text="唯一", metadata={"file_name": "b.md"}), score=0.7),
    ]
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=2)
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str=None: nodes):
            result = r.retrieve("test")
    assert [item["content"] for item in result] == ["重复", "唯一"]

def test_retrieve_empty_returns_empty():
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = []
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=3)
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str=None: nodes):
            result = r.retrieve("test")
    assert result == []


def test_retrieve_propagates_drone_metadata():
    """阶段 1：drone 向量 metadata 的售后身份字段随 Evidence 透出。"""
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [
        NodeWithScore(node=TextNode(text="内容", metadata={
            "file_name": "drone_sop_compass.md",
            "title": "SOP：指南针校准",
            "document_id": "drone_sop_compass",
            "document_type": "sop",
            "product_model": "mini_4_pro",
            "component": "compass",
            "data_type": "factual",
            "source_id": "SOURCE-008",
        }), score=0.9),
    ]
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=3)
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str=None: nodes):
            result = r.retrieve("指南针怎么校准")
    item = result[0]
    assert item["document_id"] == "drone_sop_compass"
    assert item["document_type"] == "sop"
    assert item["product_model"] == "mini_4_pro"
    assert item["component"] == "compass"
    assert item["data_type"] == "factual"
    assert item["source_id"] == "SOURCE-008"


def test_retrieve_legacy_metadata_leaves_drone_fields_none():
    """旧 collection / obsidian 库无 drone metadata 时字段为 None，向后兼容。"""
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = [
        NodeWithScore(node=TextNode(text="内容", metadata={"file_name": "a.md"}), score=0.9),
    ]
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=3)
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str=None: nodes):
            result = r.retrieve("test")
    assert result[0]["document_type"] is None
    assert result[0]["product_model"] is None
    assert result[0]["data_type"] is None
    assert result[0]["source_id"] is None
