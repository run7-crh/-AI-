# backend/tests/unit/test_diagnosis_schema.py
"""阶段 4：DiagnosisSchema 与 diagnose 节点（结构化诊断 + citation 程序校验）。"""
from unittest.mock import AsyncMock, patch

import pytest

from app.graph.nodes import (
    _format_diagnosis_for_prompt,
    _format_evidence_with_ids,
    _validate_diagnosis_citations,
    diagnose_node,
)
from app.graph.state import AgentState
from app.graph.tools import DiagnosisSchema


# ---------------------------------------------------------------------------
# Schema 解析
# ---------------------------------------------------------------------------
def test_diagnosis_schema_minimal_parse():
    schema = DiagnosisSchema(summary="机型未确认，疑似图传异常")
    assert schema.summary.startswith("机型未确认")
    assert schema.confidence == 0.0
    assert schema.needs_human_service is False
    assert schema.possible_causes == []


def test_diagnosis_schema_full_parse():
    schema = DiagnosisSchema(
        summary="Mini 4 Pro 图传黑屏，疑似固件或天线问题",
        product_model="mini_4_pro",
        fault_type="transmission_abnormal",
        possible_causes=[{"cause": "固件异常", "status": "knowledge_based", "evidence_ids": ["doc:chunk:0"]}],
        recommended_steps=[{"step": "重启设备", "expected": "图传恢复", "stop_condition": "冒烟立即停止"}],
        safety_warning="操作前取出电池",
        needs_human_service=True,
        confidence=0.7,
        citations=[{"evidence_id": "doc:chunk:0", "document_name": "troubleshooting.md", "data_type": "factual"}],
    )
    assert schema.possible_causes[0].status == "knowledge_based"
    assert schema.recommended_steps[0].stop_condition == "冒烟立即停止"
    assert schema.citations[0].data_type == "factual"


# ---------------------------------------------------------------------------
# citation 程序校验（LLM 不得创造证据 ID）
# ---------------------------------------------------------------------------
def test_validate_citations_drops_invalid_ids():
    diagnosis = {
        "summary": "s",
        "confidence": 0.8,
        "citations": [
            {"evidence_id": "doc:chunk:0", "document_name": "a.md"},
            {"evidence_id": "hallucinated-id", "document_name": "fake.md"},
        ],
    }
    cleaned = _validate_diagnosis_citations(diagnosis, {"doc:chunk:0"})
    assert [c["evidence_id"] for c in cleaned["citations"]] == ["doc:chunk:0"]
    assert cleaned["confidence"] == 0.8


def test_validate_citations_all_invalid_zeroes_confidence():
    diagnosis = {
        "summary": "s",
        "confidence": 0.9,
        "citations": [{"evidence_id": "made-up", "document_name": "x.md"}],
    }
    cleaned = _validate_diagnosis_citations(diagnosis, {"doc:chunk:0"})
    assert cleaned["citations"] == []
    assert cleaned["confidence"] == 0.0


def test_validate_citations_empty_citations_zeroes_confidence():
    """没有任何可验证引用的诊断视为不可信。"""
    cleaned = _validate_diagnosis_citations({"summary": "s", "confidence": 0.9, "citations": []}, {"doc:chunk:0"})
    assert cleaned["confidence"] == 0.0


# ---------------------------------------------------------------------------
# 证据格式化（带 id，跳过错误与空内容）
# ---------------------------------------------------------------------------
def test_format_evidence_with_ids_includes_id_and_metadata():
    items = [
        {
            "id": "doc1:chunk:0",
            "source": "troubleshooting/gps.md",
            "content": "GPS 异常时先校准罗盘。",
            "product_model": "mini_4_pro",
            "document_type": "troubleshooting",
            "data_type": "factual",
        },
    ]
    text = _format_evidence_with_ids(items)
    assert "doc1:chunk:0" in text
    assert "mini_4_pro" in text
    assert "factual" in text
    assert "GPS 异常时先校准罗盘" in text


def test_format_evidence_with_ids_skips_error_and_empty():
    items = [
        {"id": "err", "content": "x", "is_error": True},
        {"id": "empty", "content": "  "},
        {"id": "ok", "content": "正文"},
    ]
    text = _format_evidence_with_ids(items)
    assert "err" not in text
    assert "empty" not in text
    assert "正文" in text
    assert _format_evidence_with_ids([]) == "（无可用证据）"


# ---------------------------------------------------------------------------
# diagnose_node
# ---------------------------------------------------------------------------
def _local_state(**extra) -> AgentState:
    state = AgentState(
        query="刚换了 GPS 还是不定位",
        conversation_id="c1",
        history=[],
        rewritten_query="Mini 4 Pro 更换 GPS 后仍无法定位",
        retrieval_result=[
            {"id": "doc:chunk:0", "content": "定位异常排查步骤……", "source": "gps.md",
             "product_model": "mini_4_pro", "document_type": "troubleshooting", "data_type": "factual"},
        ],
        issue_profile={"product_model": "mini_4_pro", "component": "gnss", "fault_type": None,
                       "symptoms": ["无法定位"], "situation": None},
        judge_log=[],
    )
    state.update(extra)
    return state


@pytest.mark.asyncio
async def test_diagnose_node_success_with_citation_validation():
    structured = {
        "summary": "更换 GPS 后仍不定位，需排查安装与校准",
        "product_model": "mini_4_pro",
        "possible_causes": [{"cause": "模块未正确安装", "status": "inferred", "evidence_ids": ["doc:chunk:0"]}],
        "needs_human_service": True,
        "confidence": 0.65,
        "citations": [
            {"evidence_id": "doc:chunk:0", "document_name": "gps.md", "data_type": "factual"},
            {"evidence_id": "fake", "document_name": "fake.md"},
        ],
    }
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": structured}
        result = await diagnose_node(_local_state())

    assert result["diagnosis"] is not None
    assert result["diagnosis"]["confidence"] == 0.65
    # 非法 citation 被丢弃，合法保留
    assert [c["evidence_id"] for c in result["diagnosis"]["citations"]] == ["doc:chunk:0"]
    assert result["judge_log"][0]["judge_type"] == "diagnosis"
    assert result["judge_log"][0]["passed"] is True
    # 非流式（不传 stream）+ flash 模型 + 结构化输出
    assert mock_llm.call_args.kwargs.get("stream") is not True
    assert mock_llm.call_args.kwargs["model"] == "deepseek-chat"
    assert "doc:chunk:0" in mock_llm.call_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_diagnose_node_failure_degrades_to_none():
    """LLM 失败 → diagnosis=None，不抛异常（generate_local 照常运行）。"""
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("超时")
        result = await diagnose_node(_local_state())

    assert result["diagnosis"] is None
    assert result["judge_log"][0]["passed"] is False


@pytest.mark.asyncio
async def test_diagnose_node_invalid_structured_degrades_to_none():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "不是 JSON", "structured": None}
        result = await diagnose_node(_local_state())

    assert result["diagnosis"] is None
    assert result["judge_log"][0]["passed"] is False


# ---------------------------------------------------------------------------
# generate_local 注入结构化诊断
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_format_diagnosis_for_prompt_renders_sections():
    text = _format_diagnosis_for_prompt({
        "summary": "图传黑屏",
        "product_model": "mini_4_pro",
        "possible_causes": [
            {"cause": "固件异常", "status": "knowledge_based"},
            {"cause": "天线损坏", "status": "inferred"},
        ],
        "recommended_steps": [{"step": "重启", "expected": "恢复", "stop_condition": "发热停止"}],
        "safety_warning": "先取出电池",
        "confidence": 0.6,
        "needs_human_service": False,
    })
    assert "图传黑屏" in text
    assert "知识库明确" in text
    assert "推断" in text
    assert "重启" in text
    assert "先取出电池" in text
    assert "需要售后/维修介入" not in text


@pytest.mark.asyncio
async def test_generate_local_injects_diagnosis_block():
    from app.graph.nodes import generate_local_node

    state = _local_state(
        diagnosis={"summary": "定位异常", "confidence": 0.6, "needs_human_service": False},
        avg_reranker_score=0.8,
    )
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "回答正文", "structured": None}
        result = await generate_local_node(state, None)

    assert result["route_path"] == "local"
    assert "【结构化诊断" in mock_llm.call_args.kwargs["system_prompt"]
    assert "定位异常" in mock_llm.call_args.kwargs["system_prompt"]


@pytest.mark.asyncio
async def test_generate_local_without_diagnosis_keeps_legacy_prompt():
    """diagnosis=None（诊断失败/旧路径）→ 提示词与改造前一致。"""
    from app.graph.nodes import generate_local_node

    state = _local_state(avg_reranker_score=0.8)
    state = dict(state)
    state["diagnosis"] = None
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "回答正文", "structured": None}
        result = await generate_local_node(state, None)

    assert "【结构化诊断" not in mock_llm.call_args.kwargs["system_prompt"]
    assert result["route_path"] == "local"
