"""把 data/raw/test_questions.json 转换成 eval/dataset.json 格式。

生成的 v1.2 数据集包含文档级 ``expected_documents``（当前为规则推断，
``gold_status=inferred``）和可选 ``reference_answer``。未人工复核的标签不应
直接用于对外宣称 Recall 指标。

用法：
    cd backend
    python eval/build_dataset.py
"""
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

SOURCE = ROOT_DIR / "data" / "raw" / "test_questions.json"
TARGET = BACKEND_DIR / "eval" / "dataset.json"

# 阶段 5 售后评估种子。问题只引用 data/drone 已存在的文档身份和路由意图；
# expected_* 标签是测试 gold，尚未经过人工逐题复核时统一标记 inferred。
DRONE_QUESTIONS = [
    {"question": "Mini 4 Pro 的重量和续航参数是什么？", "category": "product_parameter", "difficulty": "easy", "expected_route": "local", "expected_documents": ["drone_product_mini_4_pro.md"], "expected_product_model": "mini_4_pro", "expected_intent": "product_parameter", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["product", "technical"]},
    {"question": "Matrice 350 RTK 的 RTK 弱信号怎么排查？", "category": "troubleshooting", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_troubleshooting_rtk_signal_weak.md", "drone_sop_gps_troubleshoot.md"], "expected_product_model": "matrice_350_rtk", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"]},
    {"question": "Agras T50 电池疑似鼓包，应该怎么处理？", "category": "flight_safety", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_safety_battery.md", "drone_troubleshooting_battery_swelling.md"], "expected_product_model": "agras_t50", "expected_intent": "flight_safety", "expected_safety_level": "high", "expected_escalation": True, "document_type_priority": ["safety", "troubleshooting", "sop"]},
    {"question": "Mini 4 Pro 指南针如何校准？", "category": "sop_operation", "difficulty": "easy", "expected_route": "local", "expected_documents": ["drone_sop_compass_calibration.md", "drone_technical_compass.md"], "expected_product_model": "mini_4_pro", "expected_intent": "sop_operation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["sop", "troubleshooting"]},
    {"question": "Mini 4 Pro 指南针异常应该先检查什么？", "category": "troubleshooting", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_troubleshooting_compass_abnormal.md", "drone_sop_compass_calibration.md"], "expected_product_model": "mini_4_pro", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"]},
    {"question": "Matrice 350 RTK 的 RTK 原理是什么？", "category": "technical_principle", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_technical_rtk_differential.md"], "expected_product_model": "matrice_350_rtk", "expected_intent": "technical_principle", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["technical", "product"]},
    {"question": "Agras T50 电池腐蚀还能继续飞吗？", "category": "flight_safety", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_safety_battery.md", "drone_sop_agri_battery_safe.md"], "expected_product_model": "agras_t50", "expected_intent": "flight_safety", "expected_safety_level": "high", "expected_escalation": True, "document_type_priority": ["safety", "troubleshooting", "sop"]},
    {"question": "飞行中失控并且开始坠落时，第一步做什么？", "category": "flight_safety", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_safety_abnormal_flight.md", "drone_safety_flight_basics.md"], "expected_product_model": None, "expected_intent": "flight_safety", "expected_safety_level": "high", "expected_escalation": True, "document_type_priority": ["safety", "troubleshooting", "sop"]},
    {"question": "无人机进水后还能通电测试吗？", "category": "flight_safety", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_safety_battery.md"], "expected_product_model": None, "expected_intent": "flight_safety", "expected_safety_level": "high", "expected_escalation": True, "document_type_priority": ["safety", "troubleshooting", "sop"]},
    {"question": "Mini 4 Pro 失联后的返航设置怎么配置？", "category": "sop_operation", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_sop_rth_config.md", "drone_safety_abnormal_flight.md"], "expected_product_model": "mini_4_pro", "expected_intent": "sop_operation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["sop", "troubleshooting"]},
    {"question": "Matrice 350 RTK 和 Mini 4 Pro 的返航步骤可以直接照搬吗？", "category": "cross_model_trap", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_sop_rth_config_m350.md", "drone_sop_rth_config.md"], "expected_product_model": None, "expected_intent": "sop_operation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["sop", "troubleshooting"]},
    {"question": "只说‘无人机怎么校准’，没有确认型号时应该查哪种资料？", "category": "product_model", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_sop_compass_calibration.md", "drone_sop_imu_calibration.md"], "expected_product_model": None, "expected_intent": "sop_operation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["sop", "troubleshooting"]},
    {"question": "Agras T50 的农用电池安全操作步骤是什么？", "category": "sop_operation", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_sop_agri_battery_safe.md", "drone_safety_agri_operation.md"], "expected_product_model": "agras_t50", "expected_intent": "sop_operation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["sop", "troubleshooting"]},
    {"question": "无人机飞行前需要做哪些检查？", "category": "sop_operation", "difficulty": "easy", "expected_route": "local", "expected_documents": ["drone_sop_preflight_check.md", "drone_safety_flight_basics.md"], "expected_product_model": None, "expected_intent": "sop_operation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["sop", "troubleshooting"]},
    {"question": "法规要求无人机实名登记和空域合规吗？", "category": "compliance_regulation", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_safety_caac_compliance.md"], "expected_product_model": None, "expected_intent": "compliance_regulation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["safety"]},
    {"question": "你是谁？", "category": "chitchat", "difficulty": "easy", "expected_route": "chitchat", "expected_documents": [], "expected_product_model": None, "expected_intent": "chitchat", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": []},
    {"question": "谢谢你的帮助", "category": "chitchat", "difficulty": "easy", "expected_route": "chitchat", "expected_documents": [], "expected_product_model": None, "expected_intent": "chitchat", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": []},
    {"question": "今天最新的无人机法规是什么？", "category": "time_sensitive", "difficulty": "hard", "expected_route": "online", "expected_documents": [], "expected_product_model": None, "expected_intent": "time_sensitive", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": []},
    {"question": "2026 年最新固件版本是多少？", "category": "time_sensitive", "difficulty": "hard", "expected_route": "online", "expected_documents": [], "expected_product_model": None, "expected_intent": "time_sensitive", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": []},
    {"question": "知识库没有覆盖某个新型号的电机问题时应该怎么办？", "category": "knowledge_gap", "difficulty": "medium", "expected_route": "online", "expected_documents": [], "expected_product_model": None, "expected_intent": "knowledge_gap", "expected_safety_level": "none", "expected_escalation": True, "document_type_priority": []},
    {"question": "请参考一个模拟的 Mini 4 Pro 向右漂移案例。", "category": "synthetic_case", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_case_s001_drift_right.md"], "expected_product_model": "mini_4_pro", "expected_intent": "case_reference", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["case"]},
    {"question": "模拟案例能否直接证明我的飞机就是指南针故障？", "category": "synthetic_case", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_case_s001_drift_right.md", "drone_troubleshooting_compass_abnormal.md"], "expected_product_model": "mini_4_pro", "expected_intent": "case_reference", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["case"]},
    {"question": "Matrice 350 RTK 的视觉校准失败怎么排查？", "category": "troubleshooting", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_vision_calibration.md"], "expected_product_model": "matrice_350_rtk", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"]},
    {"question": "Matrice 350 RTK 的 RTK 弱信号和 Mini 4 Pro 的 GPS 异常可以用同一参数解释吗？", "category": "cross_model_trap", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_rtk_signal_weak.md", "drone_troubleshooting_gps_abnormal.md"], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"]},
    {"question": "电池反复无法充电，按 SOP 操作后仍无效，是否需要人工升级？", "category": "escalation", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_battery_not_charging.md", "drone_sop_battery_check.md"], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": True, "document_type_priority": ["troubleshooting", "sop", "case"]},
    {"question": "我已经按步骤排查两次，遥控器仍然无法连接飞机，下一步是什么？", "category": "escalation", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_aircraft_disconnected.md", "drone_sop_link_pairing.md"], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": True, "document_type_priority": ["troubleshooting", "sop", "case"]},
    {"question": "电池在充电时发热并有异味，能否继续充电？", "category": "flight_safety", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_safety_battery.md", "drone_sop_battery_check.md"], "expected_product_model": None, "expected_intent": "flight_safety", "expected_safety_level": "high", "expected_escalation": True, "document_type_priority": ["safety", "troubleshooting", "sop"]},
    {"question": "无人机失联但还在空中，应该如何处置？", "category": "flight_safety", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_safety_abnormal_flight.md", "drone_sop_rth_config.md"], "expected_product_model": None, "expected_intent": "flight_safety", "expected_safety_level": "high", "expected_escalation": True, "document_type_priority": ["safety", "troubleshooting", "sop"]},
    {"question": "Mini 4 Pro 的视频链路黑屏怎么排查？", "category": "troubleshooting", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_troubleshooting_video_blackout.md", "drone_sop_video_link_troubleshoot.md"], "expected_product_model": "mini_4_pro", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"]},
    {"question": "Matrice 350 RTK 的返航配置步骤是什么？", "category": "sop_operation", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_sop_rth_config_m350.md"], "expected_product_model": "matrice_350_rtk", "expected_intent": "sop_operation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["sop", "troubleshooting"]},
    {"question": "Agras T50 的 RTK 中断案例只能作为模拟参考吗？", "category": "synthetic_case", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_case_s014_agri_rtk_interrupt.md"], "expected_product_model": "agras_t50", "expected_intent": "case_reference", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["case"]},
    {"question": "Mavic 3 Enterprise 的产品参数在哪里？", "category": "product_model", "difficulty": "easy", "expected_route": "local", "expected_documents": ["drone_product_mavic_3_enterprise.md"], "expected_product_model": "mavic_3_enterprise", "expected_intent": "product_parameter", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["product", "technical"]},
    {"question": "不知道具体机型时，能否直接套用 Mini 4 Pro 的校准步骤？", "category": "cross_model_trap", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_sop_compass_calibration.md"], "expected_product_model": None, "expected_intent": "sop_operation", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["sop", "troubleshooting"]},
    {"question": "请解释指南针为什么会影响飞行方向，但不要把原理当成故障诊断。", "category": "technical_principle", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_technical_compass.md"], "expected_product_model": None, "expected_intent": "technical_principle", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["technical", "product"]},
    # ── 阶段 7：Agent 业务决策场景（expected_action / expected_gaps / expected_auto_ticket）──
    {"question": "我的无人机飞不了了", "category": "insufficient_info", "difficulty": "easy", "expected_route": "followup", "expected_documents": [], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": [], "expected_action": "followup", "expected_gaps": ["product_model", "symptoms"]},
    {"question": "无人机充不进电，怎么办", "category": "insufficient_info", "difficulty": "easy", "expected_route": "followup", "expected_documents": [], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": [], "expected_action": "followup", "expected_gaps": ["product_model"]},
    {"question": "飞机总是往一边偏", "category": "insufficient_info", "difficulty": "easy", "expected_route": "followup", "expected_documents": [], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": [], "expected_action": "followup", "expected_gaps": ["product_model"]},
    {"question": "无人机的图传断了", "category": "insufficient_info", "difficulty": "easy", "expected_route": "followup", "expected_documents": [], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": [], "expected_action": "followup", "expected_gaps": ["product_model", "symptoms"]},
    {"question": "遥控器连不上飞机，怎么办", "category": "insufficient_info", "difficulty": "easy", "expected_route": "followup", "expected_documents": [], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": [], "expected_action": "followup", "expected_gaps": ["product_model"]},
    {"question": "是 Mini 4 Pro，开机正常但推杆不起飞，没有报错提示", "category": "insufficient_info_second_turn", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_troubleshooting_liftoff_abnormal.md"], "expected_product_model": "mini_4_pro", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"], "expected_action": "answer", "multi_turn": True},
    {"question": "是 Agras T50，充电器指示灯一直红色闪烁，电池装上去没反应", "category": "insufficient_info_second_turn", "difficulty": "medium", "expected_route": "local", "expected_documents": ["drone_troubleshooting_battery_not_charging.md"], "expected_product_model": "agras_t50", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"], "expected_action": "answer", "multi_turn": True},
    {"question": "Mini 4 Pro 更换 GPS 模块之后仍然无法定位，是不是需要寄修了？", "category": "service_needed", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_gps_abnormal.md"], "expected_product_model": "mini_4_pro", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"], "expected_action": "create_ticket", "expected_auto_ticket": True},
    {"question": "Agras T50 电池仓触点有明显腐蚀痕迹，充电一直失败，这种情况怎么处理？", "category": "service_needed", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_battery_not_charging.md", "drone_sop_battery_check.md"], "expected_product_model": "agras_t50", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"], "expected_action": "create_ticket", "expected_auto_ticket": True},
    {"question": "Mini 4 Pro 升级固件多次失败，现在设备无法正常开机，是否需要官方检修？", "category": "service_needed", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_firmware_update_failed.md"], "expected_product_model": "mini_4_pro", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"], "expected_action": "create_ticket", "expected_auto_ticket": True},
    {"question": "Mavic 3 Enterprise 自检报 IMU 错误，重新校准两次仍然提示错误，应该送修吗？", "category": "service_needed", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_imu_abnormal.md", "drone_sop_imu_calibration.md"], "expected_product_model": "mavic_3_enterprise", "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"], "expected_action": "create_ticket", "expected_auto_ticket": True},
    {"question": "电池充不上电，有人说是充电器问题，也有人说是电池仓触点问题，应该以官方资料为准怎么判断？", "category": "knowledge_conflict", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_battery_not_charging.md", "drone_sop_battery_check.md"], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"], "expected_action": None, "gold_notes": "知识冲突场景：action 不作硬断言，重点核对并列呈现与引用有效性"},
    {"question": "图传黑屏到底是固件问题还是天线问题？不同资料的排查顺序不一致时怎么办？", "category": "knowledge_conflict", "difficulty": "hard", "expected_route": "local", "expected_documents": ["drone_troubleshooting_video_blackout.md"], "expected_product_model": None, "expected_intent": "troubleshooting", "expected_safety_level": "none", "expected_escalation": False, "document_type_priority": ["troubleshooting", "sop", "case"], "expected_action": None, "gold_notes": "知识冲突场景：action 不作硬断言，重点核对并列呈现与引用有效性"},
]

CATEGORY_MAP = {
    "knowledge_hit": "knowledge_hit",
    "knowledge_miss": "knowledge_missing",
    "multi_hop": "multi_hop",
    "hallucination_prone": "hallucination_test",
    "fuzzy": "routing_test",
}

# 主题 → 预期来源文件名（从 data/raw 下的 .md 文件名匹配）
SOURCE_MAP = {
    "rag": "RAG 检索增强生成.md",
    "检索增强生成": "RAG 检索增强生成.md",
    "agent": "Agent.md",
    "智能体": "Agent.md",
    "agent智能体": "Agent智能体.md",
    "workflow": "Agent与Workflow的区别.md",
    "agent与workflow": "Agent与Workflow的区别.md",
    "记忆": "Agent记忆机制.md",
    "agent记忆": "Agent记忆机制.md",
    "embedding": "Embedding 向量嵌入.md",
    "向量嵌入": "Embedding 向量嵌入.md",
    "function calling": "Function Calling 函数调用.md",
    "tool calling": "Tool Calling 工具调用.md",
    "harness engineering": "Harness Engineering 驾驭工程.md",
    "驾驭工程": "Harness Engineering 驾驭工程.md",
    "llm": "LLM 大语言模型.md",
    "大语言模型": "LLM 大语言模型.md",
    "langchain": "LangChain-LangGraph.md",
    "langgraph": "LangChain-LangGraph.md",
    "loop engineering": "Loop Engineering 循环工程.md",
    "循环工程": "Loop Engineering 循环工程.md",
    "mcp": "MCP 模型上下文协议.md",
    "模型上下文协议": "MCP 模型上下文协议.md",
    "prompt": "Prompt Engineering 提示词工程.md",
    "提示词工程": "Prompt Engineering 提示词工程.md",
    "react": "ReAct 推理框架.md",
    "transformer": "Transformer.md",
    "向量数据库": "向量数据库.md",
    "微调": "微调.md",
    "lora": "微调.md",
    "qlora": "微调.md",
    "sft": "微调.md",
    "rlhf": "微调.md",
    "dpo": "微调.md",
    "幻觉": "模型幻觉.md",
}


def normalize(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text).lower()


def topic_matches(text: str, key: str) -> bool:
    """判断主题是否命中，避免 ``react`` 误匹配 ``React 19``。"""
    normalized_key = normalize(key)
    if not normalized_key:
        return False
    # React 与 ReAct 在评估语料中容易冲突：带版本号的 React 前端问题
    # 不应被标为 ReAct 知识库命中。
    if normalized_key == "react" and re.search(r"\breact\s*\d+(?:\.\d+)?", text, re.I):
        return False
    if re.search(r"\s", key):
        return normalized_key in normalize(text)
    if re.fullmatch(r"[a-z0-9]+", normalized_key):
        return bool(re.search(
            rf"(?<![a-z0-9]){re.escape(normalized_key)}(?![a-z0-9])",
            text.lower(),
        ))
    return normalized_key in normalize(text)


def infer_expected_source(question: str, notes: str) -> str | None:
    """根据问题中的关键词推断 expected_source，未命中返回 None。"""
    # 优先匹配更具体的复合主题
    ordered_keys = sorted(SOURCE_MAP.keys(), key=lambda k: -len(k))
    for key in ordered_keys:
        if topic_matches(question + " " + notes, key):
            return SOURCE_MAP[key]
    return None


def infer_expected_sources(question: str, notes: str) -> list[str]:
    """返回问题涉及的全部可验证文档，供 Recall@K/MRR 使用。

    与旧版 ``infer_expected_source`` 的“命中第一个关键词”不同，多跳问题
    可能同时依赖多个主题；这里收集所有主题并去重，顺序按关键词具体度保留。
    """
    combined = question + " " + notes
    sources: list[str] = []
    for key in sorted(SOURCE_MAP.keys(), key=lambda k: -len(k)):
        if topic_matches(combined, key):
            source = SOURCE_MAP[key]
            if source not in sources:
                sources.append(source)
    return sources


def generate_keywords(question: str, notes: str, category: str) -> list[str]:
    """基于问题生成简单的预期答案关键词。

    策略：
    - 优先保留英文/数字技术术语（RAG、Agent、LoRA、MCP 等），这些最稳定；
    - 中文按字拆分后提取 2-3 字连续片段，过滤单字停用词；
    - hallucination_test / knowledge_missing / routing_test 返回空列表。
    """
    if category in ("hallucination_test", "knowledge_missing", "routing_test"):
        return []

    text = question
    # 单字停用词
    char_stops = set(
        "是什么的了吗呢啊和跟与有在了吧之用作为它我你这个那个那种这些那些就是"
        "没有能不能行不行可以需要应该会被把让给对将从到上下中里前后主要解决"
        "问题区别差异联系关系关联核心本质基本基础概念定义流程步骤机制方式方法"
        "技术原理思想作用功能模块负责分别各自适合场景哪些为个种还于而"
    )

    keywords = []
    seen = set()

    # 1) 英文/数字术语
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9\-\.]*(?:\s+[a-zA-Z][a-zA-Z0-9\-\.]*)*", text):
        token = w.strip().lower().replace(" ", " ")
        # 过滤纯数字、过短、常见停用英文词
        if re.fullmatch(r"\d+", token) or len(token) < 2 or token in {"is", "it", "the", "a", "an"}:
            continue
        if token not in seen:
            seen.add(token)
            keywords.append(w.strip())

    # 2) 中文 bigram / trigram
    chars = [c for c in text if "\u4e00" <= c <= "\u9fa5"]
    for n in (3, 2):
        for i in range(len(chars) - n + 1):
            gram = "".join(chars[i : i + n])
            # 只要片段中不含停用字且不在句首疑问位置，就认为可能是术语
            if any(c in char_stops for c in gram):
                continue
            if gram not in seen:
                seen.add(gram)
                keywords.append(gram)

    # 3) 若前面提取太少，补一些未过滤的中文词（兜底）
    if len(keywords) < 2:
        for w in re.findall(r"[\u4e00-\u9fa5]{2,}", text):
            if any(c in char_stops for c in w):
                continue
            if w not in seen and len(w) <= 6:
                seen.add(w)
                keywords.append(w)

    return keywords[:6]


def build_drone_dataset() -> dict:
    """Build the after-sales dataset without editing any knowledge-base file."""
    known_documents = {
        path.name for path in (ROOT_DIR / "data" / "drone").rglob("*.md")
        if path.name not in {"README.md", "sources.md"}
    }
    questions = []
    cat_counts = {}
    for i, seed in enumerate(DRONE_QUESTIONS, 1):
        missing = sorted(set(seed["expected_documents"]) - known_documents)
        if missing:
            raise ValueError(f"评估题引用了不存在的 data/drone 文档: {missing}")
        cat = seed["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        # 阶段 7: 未显式给出 expected_action 的旧种子按升级标注派生
        # （expected_escalation=True → escalate，否则 answer）
        default_action = "escalate" if seed["expected_escalation"] else "answer"
        question = {
            "id": f"drone-{i:03d}",
            "question": seed["question"],
            "category": cat,
            "difficulty": seed["difficulty"],
            "expected_route": seed["expected_route"],
            "acceptable_routes": [seed["expected_route"]],
            "expected_documents": seed["expected_documents"],
            "expected_source": seed["expected_documents"][0] if seed["expected_documents"] else None,
            "expected_product_model": seed["expected_product_model"],
            "expected_intent": seed["expected_intent"],
            "expected_safety_level": seed["expected_safety_level"],
            "expected_escalation": seed["expected_escalation"],
            "document_type_priority": seed["document_type_priority"],
            "expected_action": seed.get("expected_action", default_action),
            "expected_auto_ticket": seed.get("expected_auto_ticket", False),
            "expected_gaps": seed.get("expected_gaps", []),
            "gold_status": "inferred",
            "gold_notes": seed.get(
                "gold_notes",
                "基于 data/drone 文档身份和阶段 3 路由策略生成，发布前需人工复核。",
            ),
            "reference_answer": None,
            "expected_answer_keywords": [],
            "keyword_eval": False,
            "source_type": "drone_seed",
        }
        if seed.get("multi_turn"):
            question["multi_turn"] = True
        questions.append(question)
    return {
        "version": "2.1-drone-agent",
        "schema": {
            "name": "drone_after_sales_eval",
            "retrieval_gold": "expected_documents (文档级；当前为 inferred，需人工复核)",
            "answer_gold": "reference_answer (未提供时 answer_f1 为 null)",
            "structured_gold": [
                "expected_intent", "expected_product_model", "document_type_priority",
                "expected_safety_level", "expected_escalation",
                "expected_action", "expected_auto_ticket", "expected_gaps",
            ],
        },
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "source_distribution": {"drone_seed": len(questions), "ai_expanded": 0, "from_query_log": 0},
        "category_counts": cat_counts,
        "questions": questions,
    }


def build_legacy_dataset() -> dict:
    """Keep the previous raw-question conversion available explicitly."""
    with open(SOURCE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    questions = []
    for i, q in enumerate(raw, 1):
        cat = CATEGORY_MAP.get(q["category"], q["category"])
        notes = q.get("notes", "")
        expected_documents = infer_expected_sources(q["question"], notes)
        questions.append({
            "id": f"q{i:03d}", "question": q["question"],
            "acceptable_routes": [q["expected_route"]],
            "expected_answer_keywords": generate_keywords(q["question"], notes, cat),
            "expected_source": expected_documents[0] if expected_documents else None,
            "expected_documents": expected_documents,
            "gold_status": "inferred" if expected_documents else "unlabeled",
            "reference_answer": None, "keyword_eval": False,
            "difficulty": q["difficulty"], "category": cat, "source_type": "seed",
        })
    return {
        "version": "1.2", "schema": {"name": "rag_eval", "retrieval_gold": "expected_documents", "answer_gold": "reference_answer"},
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "source_distribution": {"seed": len(questions), "ai_expanded": 0, "from_query_log": 0},
        "questions": questions,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-raw", action="store_true", help="显式生成旧 data/raw 评估集")
    args = parser.parse_args()
    dataset = build_legacy_dataset() if args.legacy_raw else build_drone_dataset()

    # 备份旧 dataset.json
    if TARGET.exists():
        backup = TARGET.with_name("dataset_seed_v1.0.json")
        if not backup.exists():
            TARGET.rename(backup)
            print(f"已备份原 dataset.json -> {backup.name}")

    with open(TARGET, "w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)

    print(f"已生成 {TARGET}，共 {len(dataset['questions'])} 题")
    print("类别分布:", dataset.get("category_counts", {}))


if __name__ == "__main__":
    main()
