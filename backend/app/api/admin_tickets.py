"""Admin ticket queue and handling API for the single-brand deployment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import require_admin
from app.api.tickets import evidence_response, event_response, ticket_response
from app.models.ticket import (
    TicketAdminEventCreate,
    TicketAdminUpdate,
    TicketDetailResponse,
    TicketResponse,
)
from app.services.ticket_service import TicketService
from app.services.ticket_store import TicketStore

router = APIRouter(prefix="/api/admin/tickets", tags=["admin-tickets"])
_service: TicketService | None = None
_store: TicketStore | None = None


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


def _map_service_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("", response_model=list[TicketResponse])
async def list_all_tickets(
    status: str | None = None,
    priority: str | None = None,
    safety_level: str | None = None,
    assignee_user_id: str | None = None,
    store: TicketStore = Depends(get_store),
    user=Depends(require_admin),
):
    return [
        ticket_response(record)
        for record in await store.list_tickets(
            status=status,
            priority=priority,
            safety_level=safety_level,
            assignee_user_id=assignee_user_id,
        )
    ]


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket_detail(
    ticket_id: str,
    store: TicketStore = Depends(get_store),
    user=Depends(require_admin),
):
    record = await store.get_ticket(ticket_id)
    if record is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    events = [event_response(event) for event in await store.list_events(ticket_id)]
    evidence = [evidence_response(item) for item in await store.list_evidence(ticket_id)]
    return TicketDetailResponse(
        ticket=ticket_response(record),
        events=events,
        evidence=evidence,
    )


@router.patch("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: str,
    payload: TicketAdminUpdate,
    service: TicketService = Depends(get_service),
    user=Depends(require_admin),
):
    try:
        record = await service.admin_update(
            ticket_id,
            actor_id=user.id,
            status=payload.status,
            priority=payload.priority,
            assignee_user_id=payload.assignee_user_id,
            resolution_summary=payload.resolution_summary,
        )
    except (LookupError, ValueError) as exc:
        raise _map_service_errors(exc) from exc
    return ticket_response(record)


@router.post("/{ticket_id}/events", response_model=TicketDetailResponse)
async def append_ticket_event(
    ticket_id: str,
    payload: TicketAdminEventCreate,
    service: TicketService = Depends(get_service),
    store: TicketStore = Depends(get_store),
    user=Depends(require_admin),
):
    try:
        if payload.event_type == "public_reply":
            record = await service.add_public_message(
                ticket_id,
                actor_type="admin",
                actor_id=user.id,
                body=payload.body,
            )
        else:
            record = await service.add_internal_note(
                ticket_id,
                actor_id=user.id,
                body=payload.body,
            )
    except (LookupError, ValueError) as exc:
        raise _map_service_errors(exc) from exc
    events = [event_response(event) for event in await store.list_events(ticket_id)]
    evidence = [evidence_response(item) for item in await store.list_evidence(ticket_id)]
    return TicketDetailResponse(
        ticket=ticket_response(record),
        events=events,
        evidence=evidence,
    )
