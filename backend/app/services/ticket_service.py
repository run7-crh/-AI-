"""Ticket lifecycle service: conversation snapshots, idempotent drafts, state machine.

Server-side data is the single source of truth for ticket snapshots. Anything a
client claims about the problem summary, safety level or sources is ignored:
the draft is built from persisted messages and query_log records only. Status
changes go through the ALLOWED_TRANSITIONS whitelist and always append an
audit event in the same transaction as the ticket update.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Optional

from app.services.ticket_store import TicketStore


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"assigned", "waiting_user", "cancelled"},
    "assigned": {"in_progress", "waiting_user", "cancelled"},
    "in_progress": {"waiting_user", "resolved_pending_confirm", "cancelled"},
    "waiting_user": {"in_progress", "cancelled"},
    "resolved_pending_confirm": {"closed", "reopened"},
    "reopened": {"assigned", "in_progress", "waiting_user"},
    "closed": set(),
    "cancelled": set(),
}

# Status transitions a regular user may trigger on their own ticket. Admins may
# trigger every whitelisted transition; agent/system actors may never change
# status themselves (they only contribute drafts, suggestions and audit events).
USER_TRANSITIONS = {"submitted", "closed", "reopened", "cancelled"}

_TRANSITION_EVENT_TYPES = {
    "submitted": "submitted",
    "assigned": "assigned",
    "in_progress": "started",
    "waiting_user": "waiting_user",
    "resolved_pending_confirm": "resolved",
    "closed": "status_changed",
    "reopened": "reopened",
    "cancelled": "cancelled",
}

_TITLE_MAX_CHARS = 60
_SUMMARY_MAX_CHARS = 800
_DRAFT_TITLE_MAX_CHARS = 100
_DRAFT_SUMMARY_MAX_CHARS = 1000
_ANSWER_DIGEST_CHARS = 240
_EVIDENCE_RETENTION_DAYS = 30


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _truncate(text: str, limit: int) -> str:
    cleaned = _one_line(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _strip_markdown(text: str) -> str:
    """Reduce a raw markdown answer to plain prose for the ticket snapshot.

    Answer text is LLM output full of ``##``/``**``/list markers that read as
    garbage in a ticket summary; fenced code blocks carry no meaning for
    human triage either and are elided outright.
    """
    cleaned = str(text or "")
    cleaned = re.sub(r"```.*?```", "（代码块略）", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", cleaned)
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\*\*([^*]*)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*\n]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    return cleaned


class TicketService:
    """Orchestrates drafts, snapshots and whitelisted status transitions."""

    def __init__(
        self,
        *,
        ticket_store: TicketStore,
        conversation_store,
        query_log_store=None,
        attachment_store=None,
        evidence_retention_days: int = _EVIDENCE_RETENTION_DAYS,
    ):
        self._ticket_store = ticket_store
        self._conversation_store = conversation_store
        self._query_log_store = query_log_store
        self._attachment_store = attachment_store
        self._evidence_retention_days = evidence_retention_days

    # ------------------------------------------------------------------ draft

    async def create_draft_from_conversation(
        self,
        user_id: str,
        conversation_id: str,
        *,
        actor_type: str = "user",
        actor_id: Optional[str] = None,
        attachment_ids: Optional[list[str]] = None,
    ) -> dict:
        """Create (or return the existing) draft ticket for one conversation.

        Idempotent per (user_id, conversation_id): repeated calls return the
        same ticket without emitting another "created" event. When attachment
        promotion fails the just-created draft is deleted as compensation so
        no orphan ticket, event or evidence rows remain.
        """
        if actor_type not in ("user", "admin", "agent"):
            raise ValueError("ticket_actor_invalid")
        conversation = await self._conversation_store.get_conversation(
            conversation_id, user_id
        )
        if conversation is None:
            raise LookupError("conversation_not_found")

        existing = await self._ticket_store.get_by_user_conversation(
            user_id, conversation_id
        )
        if existing is not None:
            return existing

        query_log_rows: list[dict] = []
        if self._query_log_store is not None:
            query_log_rows = await self._query_log_store.get_by_conversation(
                conversation_id
            )
        snapshot = self._build_snapshot(conversation, query_log_rows)
        payload = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "title": snapshot["title"],
            "problem_summary": snapshot["problem_summary"],
            "device_model": snapshot["device_model"],
            "fault_category": snapshot["fault_category"],
            "priority": "high" if snapshot["safety_level"] == "high" else "normal",
            "safety_level": snapshot["safety_level"],
            "escalation_reason": snapshot["escalation_reason"],
            "status": "draft",
        }
        try:
            ticket = await self._ticket_store.create_ticket(payload)
        except ValueError as exc:
            # A concurrent request may have won the UNIQUE(user_id,
            # conversation_id) race; treat the winner as the idempotent result.
            if str(exc) != "ticket_conversation_exists":
                raise
            ticket = await self._ticket_store.get_by_user_conversation(
                user_id, conversation_id
            )
            if ticket is None:
                raise
            return ticket
        await self._ticket_store.append_event(
            ticket_id=ticket["id"],
            actor_type=actor_type,
            actor_id=actor_id,
            event_type="created",
            from_status=None,
            to_status="draft",
            body=snapshot["problem_summary"],
            metadata={
                "conversation_id": conversation_id,
                "safety_situation": snapshot["safety_situation"],
                "escalation_required": snapshot["escalation_required"],
                "message_count": len(conversation.get("messages") or []),
            },
        )
        if self._attachment_store is not None:
            try:
                await self._promote_attachments(ticket, conversation_id, attachment_ids)
            except Exception:
                await self._ticket_store.delete_ticket(ticket["id"])
                raise
        return await self._ticket_store.get_ticket(ticket["id"]) or ticket

    async def _promote_attachments(
        self, ticket: dict, conversation_id: str, attachment_ids: Optional[list[str]]
    ) -> None:
        """Link conversation attachments as ticket evidence.

        Without explicit ids every ``ready`` attachment of the conversation is
        promoted; explicit ids are validated by the store. Retention is pushed
        out so cleanup keeps case evidence while the ticket is open.
        """
        if attachment_ids is None:
            records = await self._attachment_store.get_attachments(conversation_id)
            selected = [record.id for record in records if record.status == "ready"]
        else:
            selected = list(attachment_ids)
        if not selected:
            return
        from datetime import datetime, timezone

        retention_until = (
            datetime.now(timezone.utc) + timedelta(days=self._evidence_retention_days)
        ).isoformat()
        await self._attachment_store.promote_to_ticket(
            conversation_id, selected, ticket["id"], retention_until=retention_until
        )

    @staticmethod
    def _extract_fields(rows: list[dict]) -> dict:
        """Scan rows newest-first for safety/device fields (first hit wins)."""
        extracted: dict[str, object] = {
            "safety_level": None,
            "safety_situation": None,
            "escalation_required": None,
            "device_model": None,
            "fault_category": None,
        }
        for row in reversed(rows):
            level = row.get("safety_level")
            if extracted["safety_level"] is None and level:
                extracted["safety_level"] = str(level)
            situation = row.get("safety_situation")
            if extracted["safety_situation"] is None and situation:
                extracted["safety_situation"] = str(situation)
            escalated = row.get("escalation_required")
            if extracted["escalation_required"] is None and escalated is not None:
                extracted["escalation_required"] = bool(escalated)
            constraints = row.get("metadata_constraints")
            if isinstance(constraints, str):
                try:
                    constraints = json.loads(constraints)
                except (TypeError, ValueError):
                    constraints = None
            if isinstance(constraints, dict):
                if extracted["device_model"] is None and constraints.get("product_model"):
                    extracted["device_model"] = _one_line(str(constraints["product_model"]))
                if extracted["fault_category"] is None and (
                    constraints.get("fault_type") or constraints.get("component")
                ):
                    extracted["fault_category"] = _one_line(
                        str(constraints.get("fault_type") or constraints.get("component"))
                    )
        return extracted

    @classmethod
    def _build_snapshot(cls, conversation: dict, query_log_rows: list[dict] | None = None) -> dict:
        """Derive the ticket snapshot from persisted server-side data only.

        Message fields win; query_log records fill any gaps left by older
        conversations whose message rows predate the safety columns.
        """
        messages = conversation.get("messages") or []
        last_user = next(
            (m for m in reversed(messages) if m.get("role") == "user"), None
        )
        last_assistant = next(
            (m for m in reversed(messages) if m.get("role") == "assistant"), None
        )

        question = _one_line(str((last_user or {}).get("content") or ""))
        title = _truncate(question or conversation.get("title") or "", _TITLE_MAX_CHARS) \
            or "无人机售后支持请求"
        summary_parts = []
        if question:
            summary_parts.append(f"用户问题：{question}")
        answer = _one_line(_strip_markdown(str((last_assistant or {}).get("content") or "")))
        if answer:
            summary_parts.append(f"初步建议：{_truncate(answer, _ANSWER_DIGEST_CHARS)}")
        problem_summary = _truncate("\n".join(summary_parts) or "会话暂无消息内容。", _SUMMARY_MAX_CHARS)

        message_fields = cls._extract_fields(messages)
        log_fields = cls._extract_fields(query_log_rows or [])
        safety_level = message_fields["safety_level"] or log_fields["safety_level"] or "none"
        safety_situation = message_fields["safety_situation"] or log_fields["safety_situation"]
        escalation_required = (
            message_fields["escalation_required"]
            if message_fields["escalation_required"] is not None
            else bool(log_fields["escalation_required"])
        )
        device_model = message_fields["device_model"] or log_fields["device_model"]
        fault_category = message_fields["fault_category"] or log_fields["fault_category"]

        escalation_reason: Optional[str] = None
        if safety_level == "high":
            escalation_reason = "会话中出现高风险安全情形"
            if safety_situation:
                escalation_reason += f"（设备状态：{safety_situation}）"
        elif escalation_required:
            escalation_reason = "排查未解决，Agent 已建议联系人工或官方售后"

        return {
            "title": title,
            "problem_summary": problem_summary,
            "device_model": device_model,
            "fault_category": fault_category,
            "safety_level": safety_level,
            "safety_situation": safety_situation,
            "escalation_required": escalation_required,
            "escalation_reason": escalation_reason,
        }

    # ------------------------------------------------------------- transitions

    async def update_draft(
        self,
        ticket_id: str,
        *,
        user_id: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> dict:
        """Edit the title/description of an unsubmitted draft.

        Only the owning user may edit, only while the ticket is still a
        draft. Safety-derived fields (safety_level, escalation_reason,
        device/fault classification) are never accepted here — they stay
        server-side judgements.
        """
        ticket = await self._ticket_store.get_ticket(ticket_id, user_id=user_id)
        if ticket is None:
            raise LookupError("ticket_not_found")
        if ticket["status"] != "draft":
            raise ValueError("ticket_not_editable")
        fields: dict = {}
        if title is not None:
            cleaned_title = _truncate(_one_line(title), _DRAFT_TITLE_MAX_CHARS)
            if cleaned_title:
                fields["title"] = cleaned_title
        if summary is not None:
            cleaned_summary = summary.strip()[:_DRAFT_SUMMARY_MAX_CHARS]
            if cleaned_summary:
                fields["problem_summary"] = cleaned_summary
        if not fields:
            raise ValueError("ticket_draft_no_changes")
        return await self._ticket_store.update_ticket_fields(
            ticket_id,
            fields,
            actor_type="user",
            actor_id=user_id,
            metadata={"changed": sorted(fields)},
        )

    async def add_public_message(
        self,
        ticket_id: str,
        *,
        actor_type: str,
        actor_id: Optional[str] = None,
        body: str,
    ) -> dict:
        """Append a public supplementary message to the ticket audit trail."""
        if actor_type not in ("user", "admin"):
            raise ValueError("ticket_actor_invalid")
        ticket = await self._ticket_store.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError("ticket_not_found")
        await self._ticket_store.append_event(
            ticket_id=ticket_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type="public_message" if actor_type == "user" else "public_reply",
            from_status=None,
            to_status=None,
            body=body,
            metadata={},
        )
        return await self._ticket_store.get_ticket(ticket_id)

    async def add_internal_note(
        self,
        ticket_id: str,
        *,
        actor_id: Optional[str] = None,
        body: str,
    ) -> dict:
        """Append an admin-only internal note (never shown to the user)."""
        ticket = await self._ticket_store.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError("ticket_not_found")
        await self._ticket_store.append_event(
            ticket_id=ticket_id,
            actor_type="admin",
            actor_id=actor_id,
            event_type="internal_note",
            from_status=None,
            to_status=None,
            body=body,
            metadata={},
        )
        return await self._ticket_store.get_ticket(ticket_id)

    async def admin_update(
        self,
        ticket_id: str,
        *,
        actor_id: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        assignee_user_id: Optional[str] = None,
        resolution_summary: Optional[str] = None,
    ) -> dict:
        """Apply an admin PATCH: status via the state machine, fields directly."""
        ticket = await self._ticket_store.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError("ticket_not_found")
        fields = {
            key: value
            for key, value in (
                ("priority", priority),
                ("assignee_user_id", assignee_user_id),
                ("resolution_summary", resolution_summary),
            )
            if value is not None and value != ticket.get(key)
        }
        if status is not None and status != ticket["status"]:
            ticket = await self.transition(
                ticket_id,
                actor_type="admin",
                actor_id=actor_id,
                target_status=status,
            )
        if fields:
            ticket = await self._ticket_store.update_ticket_fields(
                ticket_id,
                fields,
                actor_type="admin",
                actor_id=actor_id,
                metadata={"changed": sorted(fields)},
            )
        return ticket

    async def transition(
        self,
        ticket_id: str,
        *,
        actor_type: str,
        actor_id: Optional[str] = None,
        target_status: str,
        body: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Apply one whitelisted status transition and audit it atomically."""
        if actor_type not in ("user", "admin", "agent", "system"):
            raise ValueError("ticket_actor_invalid")
        ticket = await self._ticket_store.get_ticket(ticket_id)
        if ticket is None:
            raise LookupError("ticket_not_found")

        current = ticket["status"]
        if target_status == current:
            return ticket
        if target_status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError("ticket_transition_not_allowed")
        if target_status == "closed" and ticket.get("safety_level") == "high" and actor_type in ("agent", "system"):
            # High-risk tickets must never be closed automatically, even by a
            # scheduled system task; only a user confirmation or an explicit
            # admin action (handled below) may close them.
            raise ValueError("ticket_high_risk_close_forbidden")
        if actor_type in ("agent", "system"):
            raise ValueError("ticket_transition_actor_forbidden")
        if actor_type == "user" and target_status not in USER_TRANSITIONS:
            raise ValueError("ticket_transition_not_allowed")

        fields: dict = {}
        event_type = _TRANSITION_EVENT_TYPES.get(target_status, "status_changed")
        if target_status == "resolved_pending_confirm":
            fields["resolved_at"] = self._ticket_store._now()
        elif target_status == "closed":
            fields["closed_at"] = self._ticket_store._now()
            if actor_type == "user":
                fields["user_confirmed_at"] = fields["closed_at"]
                event_type = "user_confirmed"
            else:
                event_type = "admin_closed"
        elif target_status == "reopened":
            fields["closed_at"] = None
            fields["user_confirmed_at"] = None
            fields["resolved_at"] = None

        return await self._ticket_store.apply_transition(
            ticket_id,
            from_status=current,
            to_status=target_status,
            fields=fields,
            event={
                "actor_type": actor_type,
                "actor_id": actor_id,
                "event_type": event_type,
                "from_status": current,
                "to_status": target_status,
                "body": body,
                "metadata": metadata or {},
            },
        )
