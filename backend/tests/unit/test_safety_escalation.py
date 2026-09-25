# backend/tests/unit/test_safety_escalation.py
"""阶段 2：安全拦截与人工升级——字段清洗、路由覆写、升级判定、片段拼接、旧状态兼容。"""
import pytest
from unittest.mock import AsyncMock, patch
from app.graph.nodes import (
    decompose_question_node,
    _compute_escalation_required,
    _build_generation_prompt,
    generate_local_node,
    generate_online_node,
    multi_step_reason_node,
    chitchat_node,
)
from app.graph.prompts import LOCAL_GEN_PROMPT, SAFETY_EMERGENCY_DIRECTIVE, HUMAN_ESCALATION_DIRECTIVE
from app.graph.builder import route_after_decompose


# ============================================================================
# decompose_question_node：安全字段提取与清洗
# ============================================================================
@pytest.mark.asyncio
async def test_decompose_extracts_safety_fields():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": {
            "is_chitchat": False, "needs_decomposition": False, "reasoning_steps": [],
            "safety_flag": True, "safety_level": "high",
            "safety_situation": "charging", "user_requests_human": False,
        }}
        out = await decompose_question_node({"rewritten_query": "电池鼓包"})
    assert out["safety_flag"] is True
    assert out["safety_level"] == "high"
    assert out["safety_situation"] == "charging"
    assert out["user_requests_human"] is False


@pytest.mark.asyncio
async def test_decompose_legacy_output_defaults_to_no_risk():
    """旧模型输出/旧 fixture 不含安全字段 → 默认无风险（向后兼容）。"""
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": {
            "is_chitchat": False, "needs_decomposition": False, "reasoning_steps": [],
        }}
        out = await decompose_question_node({"rewritten_query": "什么是 RAG"})
    assert out["safety_flag"] is False
    assert out["safety_level"] == "none"
    assert out["safety_situation"] == "unknown"


@pytest.mark.asyncio
async def test_decompose_sanitizes_illegal_values():
    """非法枚举值兜底：level 按 flag 推断，situation 归 unknown。"""
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": {
            "is_chitchat": False, "needs_decomposition": False, "reasoning_steps": [],
            "safety_flag": "yes",      # 非严格 bool
            "safety_level": "extreme", # 非法枚举
            "safety_situation": "flying",  # 非法枚举
        }}
        out = await decompose_question_node({"rewritten_query": "q"})
    assert out["safety_flag"] is False        # "yes" 非 True
    assert out["safety_level"] == "none"      # flag 未命中
    assert out["safety_situation"] == "unknown"


@pytest.mark.asyncio
async def test_decompose_level_high_without_flag_still_risky():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": {
            "is_chitchat": False, "needs_decomposition": False, "reasoning_steps": [],
            "safety_flag": False, "safety_level": "high",
        }}
        out = await decompose_question_node({"rewritten_query": "q"})
    assert out["safety_flag"] is True         # level 兜底反推
    assert out["safety_level"] == "high"


@pytest.mark.asyncio
async def test_decompose_flag_normalizes_level_to_high():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": {
            "is_chitchat": False, "needs_decomposition": False, "reasoning_steps": [],
            "safety_flag": True, "safety_level": "none",
        }}
        out = await decompose_question_node({"rewritten_query": "q"})
    assert out["safety_flag"] is True
    assert out["safety_level"] == "high"


@pytest.mark.asyncio
async def test_decompose_query_risk_is_conservative_when_model_misses_it():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "", "structured": {
            "is_chitchat": False, "needs_decomposition": False, "reasoning_steps": [],
            "safety_flag": False, "safety_level": "none", "safety_situation": "unknown",
        }}
        out = await decompose_question_node({"rewritten_query": "电池鼓包并冒烟"})
    assert out["safety_flag"] is True
    assert out["safety_level"] == "high"


# ============================================================================
# 路由：高风险覆盖闲聊快速通道
# ============================================================================
def test_route_chitchat_normal_still_fast():
    assert route_after_decompose({"is_chitchat": True, "safety_level": "none"}) == "chitchat_node"


def test_route_chitchat_high_risk_overridden():
    """高风险闲聊不走快速通道，改走检索路径。"""
    assert route_after_decompose({"is_chitchat": True, "safety_level": "high"}) == "judge_relevance"


def test_route_missing_safety_defaults_chitchat():
    """旧状态（无 safety_level 字段）闲聊路由不变。"""
    assert route_after_decompose({"is_chitchat": True}) == "chitchat_node"


# ============================================================================
# 升级判定与片段拼接
# ============================================================================
def test_escalation_default_false():
    assert _compute_escalation_required({}) is False


def test_escalation_user_requests_human():
    assert _compute_escalation_required({"user_requests_human": True}) is True


def test_escalation_prior_troubleshoot_failed():
    assert _compute_escalation_required({"prior_troubleshoot_failed": True}) is True


def test_escalation_high_risk():
    assert _compute_escalation_required({"safety_level": "high"}) is True


def test_escalation_low_confidence():
    assert _compute_escalation_required({}, low_confidence=True) is True


def test_build_prompt_no_conditions_plain():
    prompt = _build_generation_prompt("BASE", {"safety_level": "none"})
    assert prompt == "BASE"


def test_build_prompt_high_risk_appends_emergency():
    prompt = _build_generation_prompt("BASE", {"safety_level": "high"})
    assert "BASE" in prompt and SAFETY_EMERGENCY_DIRECTIVE in prompt


def test_build_prompt_escalation_appends_both():
    prompt = _build_generation_prompt("BASE", {"safety_level": "high", "user_requests_human": True})
    assert SAFETY_EMERGENCY_DIRECTIVE in prompt and HUMAN_ESCALATION_DIRECTIVE in prompt


# ============================================================================
# 生成节点：escalation_required 落 state（全路径）
# ============================================================================
@pytest.mark.asyncio
async def test_generate_local_sets_escalation_on_high_risk():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "答案", "structured": None}
        out = await generate_local_node({
            "rewritten_query": "q", "query": "q", "history": [],
            "retrieval_result": [{"content": "c", "source": "a.md", "score": 0.9}],
            "avg_reranker_score": 0.9,
            "safety_level": "high",
        })
    assert out["escalation_required"] is True
    assert out["route_path"] == "local"


@pytest.mark.asyncio
async def test_generate_local_low_confidence_triggers_escalation():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "答案", "structured": None}
        out = await generate_local_node({
            "rewritten_query": "q", "query": "q", "history": [],
            "retrieval_result": [], "avg_reranker_score": 0.3,
        })
    assert out["escalation_required"] is True  # 置信度不足


@pytest.mark.asyncio
async def test_generate_local_normal_no_escalation_and_prompt_unchanged():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "答案", "structured": None}
        state = {
            "rewritten_query": "q", "query": "q", "history": [],
            "retrieval_result": [{"content": "c", "source": "a.md", "score": 0.9}],
            "avg_reranker_score": 0.9,
        }
        out = await generate_local_node(state)
        sent_prompt = mock_llm.call_args.kwargs["system_prompt"]
    assert out["escalation_required"] is False
    assert SAFETY_EMERGENCY_DIRECTIVE not in sent_prompt   # 普通问题不拼紧急片段


@pytest.mark.asyncio
async def test_chitchat_node_sets_escalation():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "你好！", "structured": None}
        out = await chitchat_node({"query": "你好", "history": [], "safety_level": "high"})
    assert out["route_path"] == "chitchat"
    assert out["escalation_required"] is True


@pytest.mark.asyncio
async def test_generate_online_high_risk_appends_safety_directive():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "答案", "structured": None}
        out = await generate_online_node({
            "rewritten_query": "飞行中失控", "query": "飞行中失控",
            "history": [], "web_search_result": "搜索结果",
            "safety_level": "high", "safety_situation": "in_flight",
        })
    prompt = mock_llm.call_args.kwargs["system_prompt"]
    assert SAFETY_EMERGENCY_DIRECTIVE in prompt
    assert out["escalation_required"] is True


@pytest.mark.asyncio
async def test_generate_online_empty_search_requires_escalation():
    with patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"text": "有限回答", "structured": None}
        out = await generate_online_node({
            "rewritten_query": "q", "query": "q", "history": [],
            "web_search_result": [],
        })
    assert out["escalation_required"] is True


@pytest.mark.asyncio
async def test_multi_step_high_risk_appends_safety_directive():
    with patch("app.graph.nodes.retrieve", new_callable=AsyncMock) as mock_ret, \
         patch("app.graph.nodes.call_llm", new_callable=AsyncMock) as mock_llm:
        mock_ret.return_value = [{"content": "安全资料", "source": "s.md", "score": 0.9}]
        mock_llm.return_value = {"text": "答案", "structured": None}
        out = await multi_step_reason_node({
            "query": "电池冒烟", "rewritten_query": "电池冒烟", "history": [],
            "reasoning_steps": [{"sub_query": "电池冒烟如何处理"}],
            "safety_level": "high", "safety_situation": "unknown",
        }, None, rag_retriever=object())
    prompt = mock_llm.call_args.kwargs["system_prompt"]
    assert SAFETY_EMERGENCY_DIRECTIVE in prompt
    assert out["escalation_required"] is True
