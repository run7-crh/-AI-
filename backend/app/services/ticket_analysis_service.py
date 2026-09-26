# backend/app/services/ticket_analysis_service.py
"""管理端 AI 售后 Copilot：基于工单上下文与现有 RAG 生成结构化分析（阶段 6）。

设计约束（docs/agent/target_architecture.md §7/§9/§12.2/§13）：
- 复用现有 RAGRetriever（经 graph.tools.retrieve 的线程池包装）与 call_llm——
  不复制第二套检索逻辑；
- 结构化诊断复用 DiagnosisSchema，管理端扩展字段（处理建议/回复草稿/风险标记）
  由 AdminAnalysisSchema 承载；
- 结果持久化到 ticket_events（actor_type=agent, event_type=agent_suggestion），
  不新建 ai_analyses 表；metadata 只存结论与证据指针（32KB 上限，不存全文）；
- AI 仅辅助：本服务绝不改工单状态、绝不自动发送；高风险工单只给保守建议。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from pydantic import BaseModel

from app.config import settings
from app.graph.nodes import (
    _format_evidence_with_ids,
    _validate_diagnosis_citations,
    _SAFETY_KEYWORDS,
)
from app.graph.tools import DecomposeSchema, DiagnosisSchema, call_llm, retrieve

logger = logging.getLogger(__name__)

# 检索知识条数上限（管理端分析面板展示规模）
_ANALYSIS_TOP_K = 6
# agent_suggestion 事件 metadata 序列化上限（超出则丢弃证据列表，保留结论）
_METADATA_MAX_BYTES = 32 * 1024
# 建议回复的最低置信度：低于此值降级为保守模板
_REPLY_CONFIDENCE_FLOOR = 0.5

# 高风险工单的固定保守处理清单（覆盖 LLM 建议，target_architecture §13）
CONSERVATIVE_HANDLING_ADVICE = [
    "先确认设备当前状态（飞行中/已降落/充电中）：飞行中优先按官方返航/降落指引，禁止空中断电或急停电机",
    "已降落/充电中：按官方指引停止充电、取出电池并隔离检查",
    "禁止建议用户自行拆解、带电维修或绕过安全保护",
    "处理话术只引用知识库中对应机型/SOP 的官方步骤；知识库没有依据时如实说明，不得编造",
    "建议用户联系官方售后/维修中心做进一步检测，并在工单记录处理结论",
]

# 高风险/低置信时的固定回复草稿模板（人工确认后经 public_reply 发送）
CONSERVATIVE_REPLY_TEMPLATE = (
    "您好，根据您描述的情况（{summary}），为保障安全建议："
    "1）若设备仍在飞行，请先按官方指引安全降落；"
    "2）如涉及电池，请停止充电并将电池/设备移至安全位置隔离；"
    "3）请勿自行拆解或带电维修。"
    "该问题建议由官方售后进一步检测处理；如需继续协助，请在本工单补充设备型号与当前状态。"
)

# 管理端分析提示词（在 DiagnosisSchema 基础上追加客服视角字段）
ANALYSIS_PROMPT = """你是资深无人机售后支持顾问，正在辅助人工客服处理一张售后工单。
基于工单上下文与知识库检索证据，输出结构化分析（符合 AdminAnalysisSchema）。

工单上下文：
{context}

知识库检索证据（每条以【证据 id=...】开头，引用必须使用这些 id）：
{evidence}

输出要求：
1. diagnosis 部分按 DiagnosisSchema：summary/possible_causes（三分标注）/
   recommended_steps（仅官方依据步骤）/safety_warning/information_gaps/
   needs_human_service/confidence/citations（evidence_id 必须来自上方证据，禁止编造）。
2. handling_advice：给售后人员的处理建议（3-6 条，可执行、按优先级排序）。
3. suggested_reply：可直接发给用户的回复草稿（中文口语、有据可依、
   不得承诺保修/费用/维修周期，不得声称"已转人工"）。
4. risk_flags：发现的风险标记（如 high_risk、cross_model_conflict、synthetic_only_evidence）。
"""


class AdminAnalysisSchema(DiagnosisSchema):
    """管理端分析输出 = 诊断结构 + 客服视角扩展字段。"""

    handling_advice: list[str] = []   # 给售后人员的处理建议
    suggested_reply: str = ""         # 给用户的回复草稿（人工确认后才发送）
    risk_flags: list[str] = []        # 风险标记


class TicketAnalysisService:
    """工单 AI 分析编排器（图外 Service，管理端专用）。"""

    def __init__(
        self,
        *,
        ticket_store,
        conversation_store,
        query_log_store=None,
        attachment_store=None,
        rag_retriever=None,
    ):
        self._ticket_store = ticket_store
        self._conversation_store = conversation_store
        self._query_log_store = query_log_store
        self._attachment_store = attachment_store
        self._rag_retriever = rag_retriever

    # ------------------------------------------------------------------ 分析

    async def analyze(self, ticket_id: str) -> dict:
        """聚合工单上下文 → 检索 → 结构化诊断 → 安全过滤 → 持久化建议事件。"""
        ticket = await self._ticket_store.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError("ticket_not_found")
        conversation = (
            await self._conversation_store.get_conversation(ticket.get("conversation_id"))
            or {}
        )
        messages = conversation.get("messages") or []
        query_logs = (
            await self._query_log_store.get_by_conversation(ticket.get("conversation_id"))
            if self._query_log_store is not None
            else []
        )

        issue_profile, profile_source = await self._build_issue_profile(
            ticket, messages, query_logs
        )
        raw_evidence = await self._retrieve_knowledge(issue_profile, messages, ticket)
        valid_ids = {
            str(item.get("id"))
            for item in raw_evidence
            if isinstance(item, dict) and item.get("id")
        }
        diagnosis = await self._diagnose(ticket, issue_profile, messages, raw_evidence, valid_ids)
        high_risk, risk_flags = self._assess_risk(ticket, diagnosis, messages)
        handling_advice, suggested_reply = self._build_advice(
            ticket, diagnosis, high_risk, risk_flags
        )

        knowledge = [self._public_evidence(item) for item in raw_evidence]
        analysis = {
            "ticket_id": ticket_id,
            "ticket_number": ticket.get("ticket_number"),
            "summary": (diagnosis or {}).get("summary") or ticket.get("problem_summary") or "",
            "product_model": issue_profile.get("product_model"),
            "fault_category": issue_profile.get("fault_type"),
            "diagnosis": diagnosis,
            "knowledge": knowledge,
            "sop_recommendations": [
                item for item in knowledge if item.get("document_type") == "sop"
            ],
            "handling_advice": handling_advice,
            "suggested_reply": suggested_reply,
            "risk_flags": risk_flags,
            "high_risk": high_risk,
            "confidence": (diagnosis or {}).get("confidence", 0.0) if diagnosis else 0.0,
            "profile_source": profile_source,
            "model": settings.MODEL_FLASH,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "disclaimers": [
                "AI 分析仅供参考，最终处理以人工确认为准",
                "AI 不会自动发送回复或修改工单状态",
            ],
        }
        if any(item.get("data_type") == "synthetic" for item in knowledge):
            analysis["disclaimers"].append(
                "证据中包含模拟案例（synthetic），仅可作排查思路参考，不得作为确诊依据"
            )
        await self._persist_suggestion(ticket_id, analysis)
        return analysis

    # ------------------------------------------------------------- 上下文组装

    async def _build_issue_profile(
        self, ticket: dict, messages: list[dict], query_logs: list[dict]
    ) -> tuple[dict, str]:
        """优先使用工单快照字段，其次 query_log 约束；两者皆缺时用一次 LLM 补全。"""
        product_model = (ticket.get("device_model") or "").strip() or None
        fault_type = (ticket.get("fault_category") or "").strip() or None
        source = "ticket_snapshot" if (product_model or fault_type) else "unknown"

        if not (product_model and fault_type):
            for row in reversed(query_logs):
                constraints = row.get("metadata_constraints")
                if isinstance(constraints, str):
                    try:
                        constraints = json.loads(constraints)
                    except (TypeError, ValueError):
                        constraints = None
                if not isinstance(constraints, dict):
                    continue
                product_model = product_model or constraints.get("product_model")
                fault_type = fault_type or constraints.get("fault_type") or constraints.get("component")
                if product_model and fault_type:
                    source = source if source != "unknown" else "query_log"
                    break

        if not (product_model and fault_type):
            extracted = await self._extract_profile_with_llm(ticket, messages)
            product_model = product_model or extracted.get("product_model")
            fault_type = fault_type or extracted.get("fault_type")
            source = "llm_fallback" if extracted else source

        return (
            {
                "product_model": product_model,
                "fault_type": fault_type,
            },
            source,
        )

    async def _extract_profile_with_llm(self, ticket: dict, messages: list[dict]) -> dict:
        """快照字段缺失时，用一次结构化 LLM 调用补全机型/故障（复用 DecomposeSchema）。"""
        last_user = next(
            (m for m in reversed(messages) if m.get("role") == "user"), None
        )
        text = "；".join(
            part
            for part in (
                str(ticket.get("problem_summary") or ""),
                str((last_user or {}).get("content") or ""),
            )
            if part.strip()
        )[:1000]
        if not text:
            return {}
        try:
            result = await call_llm(
                system_prompt=(
                    "从无人机售后问题描述中抽取机型与故障类型。product_model 只允许 "
                    "mini_4_pro、matrice_350_rtk、agras_t50、mavic_3_enterprise 或 null；"
                    "无法确认时填 null，禁止臆造。"
                ),
                user_input=text,
                temperature=0.0,
                output_schema=DecomposeSchema,
                model=settings.MODEL_FLASH,
            )
        except Exception as exc:
            logger.warning(f"工单画像 LLM 补全失败（使用已知信息继续）: {exc}")
            return {}
        structured = (result or {}).get("structured") or {}
        if not isinstance(structured, dict):
            return {}
        return {
            "product_model": structured.get("product_model"),
            "fault_type": structured.get("fault_type"),
        }

    async def _retrieve_knowledge(
        self, issue_profile: dict, messages: list[dict], ticket: dict
    ) -> list[dict]:
        """复用现有检索器；约束来自 issue_profile，无检索器时返回空。"""
        if self._rag_retriever is None:
            return []
        last_user = next(
            (m for m in reversed(messages) if m.get("role") == "user"), None
        )
        query = "；".join(
            part
            for part in (
                str(ticket.get("problem_summary") or ""),
                str((last_user or {}).get("content") or ""),
            )
            if part.strip()
        )[:600]
        if not query:
            return []
        constraints = {
            key: value
            for key, value in issue_profile.items()
            if value
        }
        try:
            return await retrieve(
                query,
                self._rag_retriever,
                top_k=_ANALYSIS_TOP_K,
                metadata_constraints=constraints or None,
            )
        except Exception as exc:
            logger.warning(f"工单分析检索失败（继续无证据分析）: {exc}")
            return []

    # ----------------------------------------------------------------- 诊断

    async def _diagnose(
        self,
        ticket: dict,
        issue_profile: dict,
        messages: list[dict],
        raw_evidence: list[dict],
        valid_ids: set[str],
    ) -> dict | None:
        """结构化诊断（复用节点侧引用校验）；失败返回 None，不阻塞分析。"""
        last_user = next(
            (m for m in reversed(messages) if m.get("role") == "user"), None
        )
        context_lines = [
            f"- 工单号：{ticket.get('ticket_number')}",
            f"- 标题：{ticket.get('title')}",
            f"- 描述：{ticket.get('problem_summary')}",
            f"- 机型：{issue_profile.get('product_model') or '未确认'}",
            f"- 故障分类：{issue_profile.get('fault_type') or '未确认'}",
            f"- 安全等级：{ticket.get('safety_level')}",
            f"- 附件证据数：{ticket.get('evidence_count', '')}",
        ]
        if last_user:
            context_lines.append(f"- 用户最后补充：{str(last_user.get('content'))[:300]}")
        try:
            result = await call_llm(
                system_prompt=ANALYSIS_PROMPT.format(
                    context="\n".join(context_lines),
                    evidence=_format_evidence_with_ids(raw_evidence),
                ),
                user_input=str(ticket.get("problem_summary") or "请分析该工单"),
                temperature=0.2,
                output_schema=AdminAnalysisSchema,
                model=settings.MODEL_FLASH,
            )
            structured = result.get("structured")
            if not isinstance(structured, dict) or not str(structured.get("summary") or "").strip():
                raise ValueError("analysis structured output invalid")
            return _validate_diagnosis_citations(structured, valid_ids)
        except Exception as exc:
            logger.warning(f"工单 AI 诊断失败（返回无诊断分析）: {exc}")
            return None

    # ------------------------------------------------------------ 安全与建议

    def _assess_risk(self, ticket: dict, diagnosis: dict | None, messages: list[dict]) -> tuple[bool, list[str]]:
        """风险判定：high_risk 只反映真实危险信号；低置信单独成旗标。"""
        risk_flags: list[str] = []
        problem_text = "；".join(
            str(m.get("content") or "") for m in messages if m.get("role") == "user"
        )[:2000].lower()
        problem_text += str(ticket.get("problem_summary") or "").lower()
        if ticket.get("safety_level") == "high":
            risk_flags.append("ticket_safety_level_high")
        for keyword in _SAFETY_KEYWORDS:
            if str(keyword).lower() in problem_text:
                risk_flags.append(f"safety_keyword:{keyword}")
                break
        if diagnosis and diagnosis.get("safety_warning"):
            risk_flags.append("diagnosis_safety_warning")
        # 诊断缺失或置信度不足 → 单独旗标（触发保守回复，但不冒充"高风险"）
        confidence_value: float | None = None
        if diagnosis:
            try:
                confidence_value = float(diagnosis.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence_value = 0.0
        else:
            confidence_value = 0.0
        if confidence_value is None or confidence_value < _REPLY_CONFIDENCE_FLOOR:
            risk_flags.append("low_confidence")
        high_risk = any(
            flag.startswith(("ticket_safety_level_high", "safety_keyword:", "diagnosis_safety_warning"))
            for flag in risk_flags
        )
        return high_risk, risk_flags

    def _build_advice(
        self, ticket: dict, diagnosis: dict | None, high_risk: bool, risk_flags: list[str]
    ) -> tuple[list[str], str]:
        """处理建议与回复草稿：高风险或低置信一律走保守清单/模板（覆盖 LLM 输出）。"""
        if high_risk or "low_confidence" in risk_flags:
            advice = list(CONSERVATIVE_HANDLING_ADVICE)
            reply = CONSERVATIVE_REPLY_TEMPLATE.format(
                summary=str(ticket.get("problem_summary") or "相关故障")[:120]
            )
            return advice, reply
        advice = list((diagnosis or {}).get("handling_advice") or [])
        reply = str((diagnosis or {}).get("suggested_reply") or "")
        try:
            confidence = float((diagnosis or {}).get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if not reply or confidence < _REPLY_CONFIDENCE_FLOOR:
            reply = CONSERVATIVE_REPLY_TEMPLATE.format(
                summary=str(ticket.get("problem_summary") or "相关故障")[:120]
            )
        if not advice:
            advice = [
                "结合知识库证据与用户补充信息排查；证据不足时先向用户确认机型与故障细节",
                "处理后记录公开回复与内部备注，便于后续服务追溯",
            ]
        return advice, reply

    # ------------------------------------------------------------------ 输出

    @staticmethod
    def _public_evidence(item: dict) -> dict:
        """证据的公开投影：只留指针与标注，不带正文（metadata 体积可控）。"""
        return {
            "id": item.get("id"),
            "title": item.get("title") or "",
            "source": item.get("source") or "",
            "document_type": item.get("document_type"),
            "product_model": item.get("product_model"),
            "fault_type": item.get("fault_type"),
            "data_type": item.get("data_type"),
            "score": item.get("score"),
        }

    async def _persist_suggestion(self, ticket_id: str, analysis: dict) -> None:
        """把分析写入 ticket_events（agent_suggestion）；历史分析只追加不覆盖。"""
        metadata = dict(analysis)
        payload = json.dumps(metadata, ensure_ascii=False, default=str)
        if len(payload.encode("utf-8")) > _METADATA_MAX_BYTES:
            # 超限先丢证据列表（结论/建议保留），仍超限则截断序列化结果
            metadata["knowledge"] = []
            metadata["sop_recommendations"] = []
            payload = json.dumps(metadata, ensure_ascii=False, default=str)
            if len(payload.encode("utf-8")) > _METADATA_MAX_BYTES:
                payload = payload[:_METADATA_MAX_BYTES]
                metadata = {"truncated": True}
        await self._ticket_store.append_event(
            ticket_id=ticket_id,
            actor_type="agent",
            actor_id=None,
            event_type="agent_suggestion",
            from_status=None,
            to_status=None,
            body=str(analysis.get("summary") or "")[:200],
            metadata=metadata,
        )
