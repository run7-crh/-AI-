"""User-facing ticket API for the single-brand after-sales workflow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_current_user
from app.models.ticket import (
    TicketCreateFromConversation,
    TicketDetailResponse,
    TicketEventResponse,
    TicketEvidenceResponse,
    TicketMessageCreate,
    TicketResponse,
)
from app.services.ticket_service import TicketService
from app.services.ticket_store import TicketStore

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
# Tickets are always scoped through the authenticated user's id; the service
# derives every snapshot field from persisted server-side data.
_service: TicketService | None = None
_store: TicketStore | None = None

# Event types that carry internal admin context and must never reach the
# regular user detail response.
_INTERNAL_EVENT_TYPES = {"internal_note"}


def set_service(service: TicketService, store: TicketStore) -> None:
    global _service, _store
    _service = service
    _store = store


def get_service() -> TicketService:
    if _service is None:
        raise RuntimeError("TicketService not initialized")
    return _service


def get_store() -> TicketStore:
    if _store is None:
        raise RuntimeError("TicketStore not initialized")
    return _store


def _ticket_response(record: dict) -> TicketResponse:
    return TicketResponse(**record)


def _event_response(record: dict) -> TicketEventResponse:
    return TicketEventResponse(**record)


def _evidence_response(record: dict) -> TicketEvidenceResponse:
    return TicketEvidenceResponse(**record)


async def _require_owned_ticket(ticket_id: str, user) -> dict:
    record = await get_store().get_ticket(ticket_id, user_id=user.id)
    if record is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    return record


def _map_service_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.post("/from-conversation", response_model=TicketResponse, status_code=201)
async def create_ticket_from_conversation(
    payload: TicketCreateFromConversation,
    service: TicketService = Depends(get_service),
    user=Depends(get_current_user),
):
    """Create (or return the existing) draft ticket for an owned conversation."""
    try:
        record = await service.create_draft_from_conversation(
            user.id,
            payload.conversation_id,
            actor_type="user",
            actor_id=user.id,
            attachment_ids=payload.attachment_ids or None,
        )
    except (LookupError, ValueError) as exc:
        raise _map_service_errors(exc) from exc
    return _ticket_response(record)


@router.get("", response_model=list[TicketResponse])
async def list_my_tickets(
    store: TicketStore = Depends(get_store),
    user=Depends(get_current_user),
):
    return [_ticket_response(record) for record in await store.list_tickets(user_id=user.id)]


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_my_ticket(
    ticket_id: str,
    store: TicketStore = Depends(get_store),
    user=Depends(get_current_user),
):
    record = await _require_owned_ticket(ticket_id, user)
    events = [
        _event_response(event)
        for event in await store.list_events(ticket_id)
        if event.get("event_type") not in _INTERNAL_EVENT_TYPES
    ]
    evidence = [_evidence_response(item) for item in await store.list_evidence(ticket_id)]
    return TicketDetailResponse(
        ticket=_ticket_response(record),
        events=events,
        evidence=evidence,
    )


@router.post("/{ticket_id}/submit", response_model=TicketResponse)
async def submit_ticket(
    ticket_id: str,
    service: TicketService = Depends(get_service),
    user=Depends(get_current_user),
):
    await _require_owned_ticket(ticket_id, user)
    try:
        record = await service.transition(
            ticket_id,
            actor_type="user",
            actor_id=user.id,
            target_status="submitted",
        )
    except (LookupError, ValueError) as exc:
        raise _map_service_errors(exc) from exc
    return _ticket_response(record)


@router.post("/{ticket_id}/messages", response_model=TicketResponse)
async def add_ticket_message(
    ticket_id: str,
    payload: TicketMessageCreate,
    service: TicketService = Depends(get_service),
    user=Depends(get_current_user),
):
    await _require_owned_ticket(ticket_id, user)
    try:
        record = await service.add_public_message(
            ticket_id,
            actor_type="user",
            actor_id=user.id,
            body=payload.body,
        )
    except (LookupError, ValueError) as exc:
        raise _map_service_errors(exc) from exc
    return _ticket_response(record)


@router.post("/{ticket_id}/confirm-resolution", response_model=TicketResponse)
async def confirm_resolution(
    ticket_id: str,
    service: TicketService = Depends(get_service),
    user=Depends(get_current_user),
):
    await _require_owned_ticket(ticket_id, user)
    try:
        record = await service.transition(
            ticket_id,
            actor_type="user",
            actor_id=user.id,
            target_status="closed",
        )
    except (LookupError, ValueError) as exc:
        raise _map_service_errors(exc) from exc
    return _ticket_response(record)


@router.post("/{ticket_id}/reopen", response_model=TicketResponse)
async def reopen_ticket(
    ticket_id: str,
    service: TicketService = Depends(get_service),
    user=Depends(get_current_user),
):
    await _require_owned_ticket(ticket_id, user)
    try:
        record = await service.transition(
            ticket_id,
            actor_type="user",
            actor_id=user.id,
            target_status="reopened",
        )
    except (LookupError, ValueError) as exc:
        raise _map_service_errors(exc) from exc
    return _ticket_response(record)
