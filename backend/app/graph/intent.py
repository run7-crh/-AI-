"""售后意图与检索元数据策略。

保持策略为纯函数，便于在图节点和检索器之间复用；具体证据仍由已有
Evidence 结构承载，不改变 API/SSE 协议。
"""

from __future__ import annotations

INTENTS = (
    "product_parameter",
    "technical_principle",
    "troubleshooting",
    "sop_operation",
    "case_reference",
    "flight_safety",
    "compliance_regulation",
    "chitchat",
    "time_sensitive",
    "knowledge_gap",
)

INTENT_DOCUMENT_PRIORITIES = {
    "troubleshooting": ["troubleshooting", "sop", "case"],
    "flight_safety": ["safety", "troubleshooting", "sop"],
    "product_parameter": ["product", "technical"],
    "sop_operation": ["sop", "troubleshooting"],
    "case_reference": ["case"],
    "technical_principle": ["technical", "product"],
    "compliance_regulation": ["safety"],
}

MODEL_ALIASES = {
    "mini 4 pro": "mini_4_pro",
    "mini4pro": "mini_4_pro",
    "mini_4_pro": "mini_4_pro",
    "matrice 350 rtk": "matrice_350_rtk",
    "matrice350rtk": "matrice_350_rtk",
    "matrice_350_rtk": "matrice_350_rtk",
    "agras t50": "agras_t50",
    "agrast50": "agras_t50",
    "agras_t50": "agras_t50",
    "mavic 3 enterprise": "mavic_3_enterprise",
    "mavic_3_enterprise": "mavic_3_enterprise",
}

COMPONENT_TERMS = {
    "指南针": "compass", "罗盘": "compass", "compass": "compass",
    "电池": "battery", "battery": "battery",
    "rtk": "rtk", "差分": "rtk",
    "gps": "gnss", "gnss": "gnss", "定位": "gnss",
    "imu": "imu", "遥控器": "remote_controller", "remote controller": "remote_controller",
}

FAULT_TERMS = {
    "指南针异常": "compass_abnormal", "罗盘异常": "compass_abnormal",
    "rtk弱信号": "rtk_signal_abnormal", "rtk 弱信号": "rtk_signal_abnormal",
    "电池充不上": "battery_charging_abnormal", "电池无法充电": "battery_charging_abnormal",
    "电池鼓包": "battery_swelling", "固件升级失败": "firmware_update_abnormal",
}


def canonical_intent(value: object) -> str | None:
    value = str(value or "").strip().lower()
    return value if value in INTENTS else None


def infer_intent(query: str) -> str | None:
    text = str(query or "").strip().lower()
    if not text:
        return None
    if any(term in text for term in ("你好", "您好", "谢谢", "再见", "你是谁", "hello", "hi")):
        return "chitchat"
    if any(term in text for term in ("最新", "今天", "当前", "现在", "最近", "实时", "2026", "发布")):
        return "time_sensitive"
    if any(term in text for term in ("法规", "合规", "民航", "空域", "备案", "实名")):
        return "compliance_regulation"
    if any(term in text for term in ("飞行安全", "安全问题", "飞行中", "失控", "坠落", "飞丢", "失联", "超限飞行")):
        return "flight_safety"
    if any(term in text for term in ("模拟案例", "案例", "曾经", "参考")):
        return "case_reference"
    if any(term in text for term in ("怎么操作", "如何操作", "步骤", "校准", "配置", "设置", "sop")):
        return "sop_operation"
    if any(term in text for term in ("故障", "异常", "报错", "问题", "无法", "不能", "弱信号", "不充电", "排查")):
        return "troubleshooting"
    if any(term in text for term in ("参数", "重量", "续航", "尺寸", "规格", "支持多少")):
        return "product_parameter"
    if any(term in text for term in ("原理", "为什么", "工作机制", "如何实现")):
        return "technical_principle"
    if any(term in text for term in ("知识库没有", "没有相关资料", "未覆盖", "查不到")):
        return "knowledge_gap"
    return None


def extract_constraints(query: str, structured: dict | None = None) -> dict[str, str]:
    text = str(query or "").lower()
    constraints: dict[str, str] = {}
    for alias, model in sorted(MODEL_ALIASES.items(), key=lambda pair: -len(pair[0])):
        if alias in text:
            constraints["product_model"] = model
            break
    structured = structured or {}
    # 只有用户文本确认过的机型才能进入硬过滤；防止模型臆造机型。
    model = str(structured.get("product_model") or "").strip().lower()
    if model in MODEL_ALIASES.values() and "product_model" in constraints and constraints["product_model"] == model:
        constraints["product_model"] = model
    for term, component in COMPONENT_TERMS.items():
        if term in text:
            constraints.setdefault("component", component)
            break
    for term, fault in FAULT_TERMS.items():
        if term in text:
            constraints.setdefault("fault_type", fault)
            break
    for field in ("component", "fault_type"):
        value = str(structured.get(field) or "").strip()
        if value and value != "unknown":
            constraints.setdefault(field, value)
    return constraints


def metadata_policy(intent: str | None, query: str, structured: dict | None = None) -> tuple[dict[str, str], list[str]]:
    intent = canonical_intent(intent) or infer_intent(query)
    constraints = extract_constraints(query, structured)
    return constraints, list(INTENT_DOCUMENT_PRIORITIES.get(intent or "", []))
