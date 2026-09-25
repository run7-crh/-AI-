"""评估口径回归测试：Recall/MRR 与关键词辅助信号分离。"""

import asyncio
import json
import math
from unittest.mock import AsyncMock, patch

import pytest
from pathlib import Path

from eval.run_eval import (
    _retrieval_metrics,
    _token_f1,
    _document_label_variants,
    _citation_text,
    aggregate,
    print_summary,
    stream_chat,
    _classification_accuracy,
    _safety_recall,
    _cross_model_contamination_count,
)


def _eval_result(**overrides):
    result = {
        "id": "q1", "question": "RAG?", "category": "knowledge_hit",
        "difficulty": "easy", "route_correct": True,
        "answer_relevance": None, "keyword_coverage": None,
        "citation_correct": None, "retrieval_success": None,
        "retrieval_hit_at_3": True, "retrieval_non_empty": True,
        "retrieval_recall_at_1": 1.0, "retrieval_recall_at_3": 1.0,
        "retrieval_recall_at_5": 1.0, "retrieval_mrr": 1.0,
        "hallucination_suspected": None, "expected_routes": ["local"],
        "actual_route": "local", "error": None,
        "expected_documents": ["RAG.md"], "gold_status": "reviewed",
        "retrieved_doc_ids": ["RAG.md"], "final_answer": "RAG", "has_source": True,
    }
    result.update(overrides)
    return result


def test_retrieval_metrics_use_document_labels_and_rank():
    metrics = _retrieval_metrics(
        ["target.md", "second.md"],
        ["other.md", "target.md", "target.md"],
    )
    assert metrics["hit_at_1"] is False
    assert metrics["hit_at_3"] is True
    assert metrics["recall_at_3"] == 0.5
    assert metrics["reciprocal_rank"] == 0.5
    assert metrics["first_relevant_rank"] == 2
    assert 0 < metrics["ndcg_at_3"] < 1


def test_retrieval_ranking_deduplicates_documents_by_first_occurrence():
    metrics = _retrieval_metrics(
        ["TARGET.md", "target.md", "second.md"],
        [r"C:\notes\Target.md", "/docs/TARGET.md", "other.md", "second.md"],
    )
    assert metrics["retrieved_documents"] == [r"C:\notes\Target.md", "other.md", "second.md"]
    assert metrics["recall_at_1"] == 0.5
    assert metrics["recall_at_3"] == 1.0
    assert metrics["reciprocal_rank"] == 1.0
    assert metrics["ndcg_at_3"] == pytest.approx(1.5 / (1 + 1 / math.log2(3)))


def test_retrieval_ndcg_is_one_for_ideal_document_order():
    metrics = _retrieval_metrics(["a.md", "b.md"], ["b.md", "a.md", "other.md"])
    for k in (1, 3, 5):
        assert metrics[f"ndcg_at_{k}"] == 1.0


def test_retrieval_metrics_without_labels_are_not_applicable():
    metrics = _retrieval_metrics([], ["anything.md"])
    assert metrics["applicable"] is False
    assert metrics["recall_at_3"] == 0.0
    assert metrics["reciprocal_rank"] == 0.0


def test_token_f1_is_explicitly_lexical():
    score = _token_f1("RAG 使用外部知识", "RAG 使用外部知识增强回答")
    assert score is not None
    assert 0 < score < 1
    assert _token_f1("答案", None) is None


def test_document_label_variants_match_title_without_extension():
    assert _document_label_variants("docs/RAG 检索增强生成.md") == {
        "rag 检索增强生成.md",
        "rag 检索增强生成",
    }


def test_citation_text_requires_explicit_source_marker():
    assert _citation_text("正文提到 Agent，但没有引用") == ""
    assert _citation_text("答案【来源：Agent】（标题：Agent）") == "agent"


def test_aggregate_does_not_report_keyword_hit_as_answer_relevance(capsys):
    result = aggregate([_eval_result()])
    assert result["summary"]["answer_relevance"] is None
    assert result["summary"]["retrieval_recall_at_3"] == 1.0
    assert result["summary"]["retrieval_success_rate"] is None
    print_summary(result, "test")
    assert "N/A / N/A / N/A" in capsys.readouterr().out


def test_aggregate_deprecated_retrieval_success_stays_null_for_legacy_results():
    report = aggregate([_eval_result(retrieval_success=True)])
    assert report["summary"]["retrieval_success_rate"] is None


def test_aggregate_retrieval_denominator_counts_applicable_recall_results():
    report = aggregate([
        _eval_result(),
        _eval_result(id="q2", expected_documents=[], retrieval_recall_at_3=None),
    ])
    assert report["summary"]["retrieval_denom"] == 1


def test_aggregate_warnings_reflect_reviewed_labels_and_measured_f1():
    report = aggregate([_eval_result(answer_relevance=0.75, hallucination_suspected=False)])
    warnings = "\n".join(report["warnings"])
    assert "未提供 reference_answer" not in warnings
    assert "gold_status=inferred" not in warnings


def test_aggregate_missing_hallucination_check_is_not_zero_hallucinations(capsys):
    report = aggregate([_eval_result()])
    assert report["summary"]["hallucination_count"] is None
    assert report["summary"]["hallucination_denom"] == 0
    assert report["by_category"]["knowledge_hit"]["hallucination_count"] is None
    print_summary(report, "test")
    assert "疑似幻觉数:        N/A" in capsys.readouterr().out


def test_aggregate_hallucination_coverage_counts_only_boolean_judgements():
    report = aggregate([
        _eval_result(),
        _eval_result(id="q2", hallucination_suspected=False),
        _eval_result(id="q3", hallucination_suspected=True),
        _eval_result(id="q4", hallucination_suspected="false"),
    ])
    assert report["summary"]["hallucination_count"] == 1
    assert report["summary"]["hallucination_denom"] == 2
    assert report["summary"]["hallucination_coverage"] == 0.5


def _sse_client(events):
    class FakeResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_lines(self):
            for event in events:
                yield "data: " + json.dumps(event)

    class FakeClient:
        def stream(self, method, path, json):
            return FakeResponse()

    return FakeClient()


def test_stream_chat_filters_web_and_error_evidence_from_local_documents():
    sources = [
        {"source_type": "web", "title": "RAG.md", "url": "https://example.test/rag"},
        {"source_type": "local", "source": "RAG.md", "content": "local"},
        {"source_type": "local", "source": "broken.md", "is_error": True},
        {"source": "legacy.md"},
        {"source": "legacy-web", "url": "https://example.test/legacy"},
        {"source": "https://example.test/legacy-source"},
    ]
    client = _sse_client([{"type": "meta", "data": {"sources": sources}}])
    result = asyncio.run(stream_chat(client, "conv", "question"))
    assert result["retrieved_doc_ids"] == ["RAG.md", "legacy.md"]
    assert result["retrieved_sources"] == sources


@pytest.mark.parametrize("judgement, expected", [(False, False), (True, True), ("false", None), (0, None), (None, None)])
def test_stream_chat_accepts_only_boolean_hallucination_judgement(judgement, expected):
    client = _sse_client([{
        "type": "meta",
        "data": {"judge_log": [
            {"raw_output": {"has_hallucination": True}},
            {"raw_output": {"has_hallucination": judgement}},
        ]},
    }])
    result = asyncio.run(stream_chat(client, "conv", "question"))
    assert result["has_hallucination"] is expected


def test_stream_chat_returns_canonical_answer_on_done_without_fixed_delay():
    client = _sse_client([
        {"type": "token", "data": "partial"},
        {"type": "final", "data": {"answer": "complete"}},
        {"type": "done", "data": {}},
    ])
    with patch("eval.run_eval.asyncio.sleep", new_callable=AsyncMock) as sleep:
        result = asyncio.run(stream_chat(client, "conv", "question"))
    assert result["final_answer"] == "complete"
    assert result["error"] is None
    sleep.assert_not_awaited()


def test_new_after_sales_metrics_preserve_null_denominators():
    results = [
        _eval_result(
            expected_intent="troubleshooting", actual_intent="troubleshooting",
            expected_product_model="mini_4_pro", actual_product_model="mini_4_pro",
            expected_document_type_priority=["troubleshooting", "sop"],
            actual_document_type_priority=["troubleshooting", "sop"],
            expected_safety_level="high", actual_safety_level="high",
            expected_escalation=True, actual_escalation=True,
        )
    ]
    assert _classification_accuracy(results, "intent") == 1.0
    assert _classification_accuracy(results, "product_model") == 1.0
    assert _classification_accuracy(results, "document_type_priority") == 1.0
    assert _safety_recall(results) == 1.0
    assert _classification_accuracy(results, "escalation") == 1.0
    assert _cross_model_contamination_count(results) == 0
    assert _classification_accuracy([_eval_result()], "intent") is None


def test_cross_model_contamination_counts_incompatible_explicit_metadata():
    result = _eval_result(
        expected_product_model="mini_4_pro",
        retrieved_sources=[
            {"source_type": "local", "product_model": "matrice_350_rtk"},
            {"source_type": "local", "product_model": "all"},
        ],
    )
    assert _cross_model_contamination_count([result]) == 1


def test_drone_dataset_has_required_structured_gold_fields():
    dataset_path = Path(__file__).parents[2] / "eval" / "dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert dataset["version"] == "2.0-drone-after-sales"
    assert len(dataset["questions"]) >= 30
    required = {
        "question", "category", "difficulty", "expected_route", "acceptable_routes",
        "expected_documents", "expected_product_model", "expected_intent",
        "expected_safety_level", "expected_escalation", "gold_status",
    }
    for question in dataset["questions"]:
        assert required <= question.keys()
    categories = {question["category"] for question in dataset["questions"]}
    assert {"product_parameter", "troubleshooting", "sop_operation", "flight_safety", "compliance_regulation", "chitchat", "time_sensitive", "knowledge_gap", "cross_model_trap", "synthetic_case"} <= categories
