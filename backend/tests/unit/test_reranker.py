import pytest
from unittest.mock import patch, MagicMock
from llama_index.core.schema import NodeWithScore, TextNode
from app.rag.retriever import HuaweiReranker

def test_reranker_sorts_by_score_desc():
    reranker = HuaweiReranker()
    nodes = [
        NodeWithScore(node=TextNode(text="低分内容"), score=0.1),
        NodeWithScore(node=TextNode(text="高分内容"), score=0.9),
        NodeWithScore(node=TextNode(text="中分内容"), score=0.5),
    ]
    with patch.object(reranker, "_call_huawei_rerank",
                      return_value={"scores": [0.1, 0.9, 0.5]}):
        result = reranker._postprocess_nodes(nodes, query_str="test")
    assert result[0].node.get_content() == "高分内容"
    assert result[1].node.get_content() == "中分内容"
    assert result[2].node.get_content() == "低分内容"

def test_reranker_empty_nodes_returns_empty():
    reranker = HuaweiReranker()
    assert reranker._postprocess_nodes([], query_str="test") == []

def test_reranker_class_name():
    assert HuaweiReranker.class_name() == "HuaweiReranker"
