# backend/tests/unit/test_builder.py
import pytest
from unittest.mock import MagicMock
from app.graph.builder import (
    build_graph, route_after_decompose, route_after_relevance,
    route_after_rag_retrieve, route_after_quality,
)
from langgraph.graph import END

def test_route_after_decompose_true():
    state = {"needs_decomposition": True}
    assert route_after_decompose(state) == "multi_step_reason"

def test_route_after_decompose_false():
    state = {"needs_decomposition": False}
    assert route_after_decompose(state) == "judge_relevance"

def test_route_after_relevance_true():
    state = {"is_relevant": True}
    assert route_after_relevance(state) == "rag_retrieve"

def test_route_after_relevance_false():
    state = {"is_relevant": False}
    assert route_after_relevance(state) == "web_search"

def test_route_after_rag_retrieve_pass():
    state = {"rag_quality_pass": True}
    assert route_after_rag_retrieve(state) == "generate_answer"

def test_route_after_rag_retrieve_fail():
    state = {"rag_quality_pass": False}
    assert route_after_rag_retrieve(state) == "web_search"

def test_route_after_quality_pass():
    state = {"answer_quality_pass": True, "hallucination_flag": False, "route_path": "local"}
    assert route_after_quality(state) == END

def test_route_after_quality_fail_local_goes_fallback():
    state = {"answer_quality_pass": False, "hallucination_flag": True, "route_path": "local"}
    assert route_after_quality(state) == "fallback_online"

def test_route_after_quality_fail_online_ends():
    state = {"answer_quality_pass": False, "hallucination_flag": True, "route_path": "online"}
    assert route_after_quality(state) == END

def test_build_graph_returns_compiled():
    mock_retriever = MagicMock()
    graph = build_graph(mock_retriever)
    # 验证是 compiled graph
    assert hasattr(graph, "ainvoke")
    assert hasattr(graph, "astream_events")
