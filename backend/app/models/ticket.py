"""Domain models and public response schemas for after-sales tickets."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TicketStatus = Literal[
    "draft",
    "submitted",
    "assigned",
    "in_progress",
    "waiting_user",
    "resolved_pending_confirm",
    "closed",
    "reopened",
    "cancelled",
]
TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketActorType = Literal["user", "admin", "agent", "system"]


class TicketResponse(BaseModel):
    id: str
    ticket_number: str
    user_id: str
    conversation_id: str
    title: str
    problem_summary: str
    device_model: str | None = None
    serial_number: str | None = None
    firmware_version: str | None = None
    fault_category: str | None = None
    priority: TicketPriority
    safety_level: str
    escalation_reason: str | None = None
    assignee_user_id: str | None = None
    status: TicketStatus
    resolution_summary: str | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    user_confirmed_at: datetime | None = None


class TicketEventResponse(BaseModel):
    id: str
    ticket_id: str
    actor_type: TicketActorType
    actor_id: str | None = None
    event_type: str
    from_status: TicketStatus | None = None
    to_status: TicketStatus | None = None
    body: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class TicketEvidenceResponse(BaseModel):
    id: str
    ticket_id: str
    evidence_type: Literal["attachment", "message", "query_log"]
    evidence_id: str
    created_at: datetime
