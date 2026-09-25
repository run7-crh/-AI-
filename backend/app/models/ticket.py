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


class TicketCreateFromConversation(BaseModel):
    """User request to open (or fetch) the draft ticket of one conversation.

    Deliberately carries no summary/safety/source fields: the service derives
    the snapshot from persisted server-side data only.
    """

    conversation_id: str
    attachment_ids: list[str] = Field(default_factory=list)


class TicketMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class TicketAdminUpdate(BaseModel):
    """Admin PATCH payload. Only these four fields are updatable."""

    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assignee_user_id: str | None = None
    resolution_summary: str | None = None


class TicketAdminEventCreate(BaseModel):
    event_type: Literal["public_reply", "internal_note"]
    body: str = Field(min_length=1, max_length=4000)


class TicketDraftUpdate(BaseModel):
    """Owner edit of an unsubmitted draft (title/description only).

    Safety-derived fields are intentionally absent: they stay server-side
    judgements and cannot be overridden by the client.
    """

    title: str | None = Field(default=None, max_length=100)
    problem_summary: str | None = Field(default=None, max_length=1000)


class TicketDetailResponse(BaseModel):
    ticket: TicketResponse
    events: list[TicketEventResponse] = Field(default_factory=list)
    evidence: list[TicketEvidenceResponse] = Field(default_factory=list)
