import pytest
from unittest.mock import patch, MagicMock
from llama_index.core.schema import NodeWithScore, TextNode
from app.rag.retriever import BGEReranker

def test_reranker_sorts_by_score_desc():
    reranker = BGEReranker()
    nodes = [
        NodeWithScore(node=TextNode(text="低分内容"), score=0.1),
        NodeWithScore(node=TextNode(text="高分内容"), score=0.9),
        NodeWithScore(node=TextNode(text="中分内容"), score=0.5),
    ]
    mock_model = MagicMock()
    mock_model.predict = MagicMock(return_value=[0.1, 0.9, 0.5])
    with patch("app.rag.retriever.get_cross_encoder", return_value=mock_model):
        result = reranker._postprocess_nodes(nodes, query_str="test")
    assert result[0].node.get_content() == "高分内容"
    assert result[1].node.get_content() == "中分内容"
    assert result[2].node.get_content() == "低分内容"

def test_reranker_empty_nodes_returns_empty():
    reranker = BGEReranker()
    assert reranker._postprocess_nodes([], query_str="test") == []

def test_reranker_class_name():
    assert BGEReranker.class_name() == "BGEReranker"
