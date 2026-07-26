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

def test_retrieve_empty_returns_empty():
    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.retrieve.return_value = []
    with patch("app.rag.retriever.VectorIndexRetriever", return_value=mock_retriever):
        r = RAGRetriever(mock_index, top_k=3)
        with patch.object(r.reranker, "_postprocess_nodes", side_effect=lambda nodes, query_str=None: nodes):
            result = r.retrieve("test")
    assert result == []
