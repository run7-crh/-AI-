import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import ExitStack
from llama_index.core.schema import NodeWithScore, TextNode

from app.graph.builder import route_after_decompose
from app.graph.intent import infer_intent, metadata_policy
from app.graph.nodes import decompose_question_node, rag_retrieve_node
from app.rag.retriever import RAGRetriever


@pytest.mark.asyncio
async def test_decompose_classifies_after_sales_intent_and_constraints():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {
            "text": "",
            "structured": {
                "is_chitchat": False,
                "needs_decomposition": False,
                "reasoning_steps": [],
                "intent": "troubleshooting",
                "product_model": "mini_4_pro",
                "component": "compass",
                "fault_type": "compass_abnormal",
                "safety_flag": False,
                "safety_level": "none",
                "safety_situation": "unknown",
                "user_requests_human": False,
            },
        }
        result = await decompose_question_node({"rewritten_query": "Mini 4 Pro 指南针异常"})
    assert result["intent"] == "troubleshooting"
    assert result["metadata_constraints"] == {
        "product_model": "mini_4_pro",
        "component": "compass",
        "fault_type": "compass_abnormal",
    }
    assert result["document_type_priority"][:3] == ["troubleshooting", "sop", "case"]


def test_route_safety_is_checked_before_intent():
    assert route_after_decompose({
        "intent": "chitchat", "is_chitchat": True, "safety_level": "high",
    }) == "judge_relevance"


@pytest.mark.parametrize(("query", "expected"), [
    ("Mini 4 Pro 指南针校准", "sop_operation"),
    ("Matrice 350 RTK 的 RTK 弱信号", "troubleshooting"),
    ("Agras T50 电池问题", "troubleshooting"),
    ("这是什么飞行安全问题", "flight_safety"),
    ("你好", "chitchat"),
])
def test_after_sales_scenario_intent_fallbacks(query, expected):
    assert infer_intent(query) == expected


def test_metadata_policy_does_not_invent_unconfirmed_model():
    constraints, priority = metadata_policy("sop_operation", "指南针怎么校准")
    assert "product_model" not in constraints
    assert priority == ["sop", "troubleshooting"]


@pytest.mark.asyncio
async def test_rag_retrieve_passes_intent_metadata_policy():
    retriever = MagicMock()
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_retrieve:
        mock_retrieve.return_value = [{"content": "c", "score": 0.8}]
        out = await rag_retrieve_node({
            "rewritten_query": "Mini 4 Pro 指南针异常",
            "intent": "troubleshooting",
            "metadata_constraints": {"product_model": "mini_4_pro", "component": "compass"},
            "document_type_priority": ["troubleshooting", "sop", "case"],
        }, retriever)
    kwargs = mock_retrieve.call_args.kwargs
    assert kwargs["metadata_constraints"]["product_model"] == "mini_4_pro"
    assert kwargs["document_type_priority"] == ["troubleshooting", "sop", "case"]
    assert out["retrieval_result"]


def _retriever_with_nodes(nodes):
    index = MagicMock()
    vector = MagicMock()
    vector.retrieve.return_value = nodes
    stack = ExitStack()
    stack.enter_context(patch("app.rag.retriever.VectorIndexRetriever", return_value=vector))
    retriever = RAGRetriever(index, top_k=3)
    stack.enter_context(patch.object(retriever.reranker, "_postprocess_nodes", side_effect=lambda items, query_str=None: items))
    return retriever, stack


def test_metadata_priority_prefers_troubleshooting_for_fault_queries():
    nodes = [
        NodeWithScore(node=TextNode(text="sop", metadata={"file_name": "sop.md", "document_type": "sop"}), score=0.95),
        NodeWithScore(node=TextNode(text="trouble", metadata={"file_name": "t.md", "document_type": "troubleshooting"}), score=0.8),
        NodeWithScore(node=TextNode(text="case", metadata={"file_name": "c.md", "document_type": "case", "data_type": "synthetic"}), score=0.79),
    ]
    retriever, stack = _retriever_with_nodes(nodes)
    result = retriever.retrieve("电池故障", metadata_constraints={}, document_type_priority=["troubleshooting", "sop", "case"])
    stack.close()
    assert result[0]["document_type"] == "troubleshooting"
    assert result[2]["data_type"] == "synthetic"


def test_model_filter_keeps_all_docs_and_falls_back_without_cross_model_steps():
    nodes = [
        NodeWithScore(node=TextNode(text="other", metadata={"file_name": "m350.md", "document_type": "sop", "product_model": "matrice_350_rtk"}), score=0.99),
        NodeWithScore(node=TextNode(text="generic", metadata={"file_name": "all.md", "document_type": "sop", "product_model": "all"}), score=0.7),
    ]
    retriever, stack = _retriever_with_nodes(nodes)
    result = retriever.retrieve("Mini 4 Pro 操作", metadata_constraints={"product_model": "mini_4_pro"})
    stack.close()
    assert result
    assert all(item["product_model"] in ("mini_4_pro", "all") for item in result)


def test_metadata_filter_falls_back_to_broader_same_model_results():
    nodes = [
        NodeWithScore(node=TextNode(text="same model", metadata={"file_name": "mini.md", "product_model": "mini_4_pro", "component": "battery"}), score=0.8),
    ]
    retriever, stack = _retriever_with_nodes(nodes)
    result = retriever.retrieve(
        "Mini 4 Pro 指南针故障",
        metadata_constraints={"product_model": "mini_4_pro", "component": "compass"},
    )
    stack.close()
    assert result and result[0]["product_model"] == "mini_4_pro"


def test_unconfirmed_model_does_not_apply_specific_model_filter():
    nodes = [
        NodeWithScore(node=TextNode(text="m350", metadata={"file_name": "m350.md", "product_model": "matrice_350_rtk"}), score=0.9),
        NodeWithScore(node=TextNode(text="mini", metadata={"file_name": "mini.md", "product_model": "mini_4_pro"}), score=0.8),
    ]
    retriever, stack = _retriever_with_nodes(nodes)
    result = retriever.retrieve("指南针怎么校准", metadata_constraints={})
    stack.close()
    assert {item["product_model"] for item in result} == {"matrice_350_rtk", "mini_4_pro"}
