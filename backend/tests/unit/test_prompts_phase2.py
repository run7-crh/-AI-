# backend/tests/unit/test_prompts_phase2.py
"""阶段 2：售后提示词测试——人设、纪律、引用规则、format 安全。"""
import pytest
from app.graph.prompts import (
    LOCAL_GEN_PROMPT,
    ONLINE_GEN_PROMPT,
    CHITCHAT_PROMPT,
    MULTI_STEP_PROMPT,
    DECOMPOSE_PROMPT,
    SAFETY_EMERGENCY_DIRECTIVE,
    HUMAN_ESCALATION_DIRECTIVE,
)


def test_local_prompt_formats_without_error():
    out = LOCAL_GEN_PROMPT.format(query="Mini 4 Pro 指南针异常", context="【来源：a.md】内容")
    assert "无人机售后技术支持专员" in out
    assert "Mini 4 Pro 指南针异常" in out


def test_local_prompt_has_drone_domain_disciplines():
    for keyword in (
        "互不通用",            # 不跨机型
        "（知识库明确）", "（推断）", "（无法确认）",  # 三分标注
        "模拟案例",            # synthetic 标注
        "禁止编造",            # 不编造政策/步骤
        "已确认安全",          # 禁写
        "[来源：文档名]",       # 引用格式
        "已转人工",            # 禁称
        "【问题判断】", "【安全提醒】", "【建议排查】", "【可能原因】",
        "【需要补充的信息】", "【来源依据】", "【是否建议转人工】",  # 七段结构
        "飞行中", "已降落", "充电中", "未知状态",  # 安全三态+未知
        "断电",                # 禁止笼统断电
    ):
        assert keyword in LOCAL_GEN_PROMPT, f"缺少关键约束: {keyword}"


def test_online_prompt_keeps_domain_constraints():
    out = ONLINE_GEN_PROMPT.format(query="q", search_result="[1] 结果")
    assert "不承诺保修政策" in out
    assert "官方渠道核验" in out
    assert "禁止声称" in out and "已转人工" in out
    assert "安全规则优先" in out  # 安全优先级不被联网覆盖


def test_chitchat_prompt_persona_and_safety_fallback():
    out = CHITCHAT_PROMPT.format(query="你好")
    assert "无人机售后技术支持" in out
    assert "联系官方售后" in out      # 紧急情形兜底提醒


def test_multi_step_prompt_has_aftermarket_disciplines():
    out = MULTI_STEP_PROMPT.format(sub_queries="1. a", context="c", query="q")
    assert "售后纪律" in out
    assert "（无法确认）" in out


def test_decompose_prompt_safety_fields_and_format_safety():
    out = DECOMPOSE_PROMPT.format(query="电池鼓包了")
    assert "safety_flag" in out and "safety_level" in out
    assert "in_flight/landed/charging/unknown" in out
    assert "user_requests_human" in out
    # 输出 JSON 示例占位符双写后能通过 format
    assert "{{" not in out  # format 后不应残留双花括号


def test_condition_directives_have_no_braces():
    # 条件片段在 format 之后拼接，自身不得含花括号
    assert "{" not in SAFETY_EMERGENCY_DIRECTIVE
    assert "{" not in HUMAN_ESCALATION_DIRECTIVE
    assert "禁止建议空中断电或急停电机" in SAFETY_EMERGENCY_DIRECTIVE
    assert "禁止声称" in HUMAN_ESCALATION_DIRECTIVE and "已创建工单" in HUMAN_ESCALATION_DIRECTIVE
