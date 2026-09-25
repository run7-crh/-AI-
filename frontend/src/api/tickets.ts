import type { Ticket, TicketDetail } from '@/types'
import { apiFetch } from './http'

async function ensureOk(response: Response): Promise<Response> {
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response
}

function jsonRequest(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

/**
 * Create (or fetch the existing) draft ticket for an owned conversation.
 * The server derives every snapshot field; the client only points at the
 * conversation and optionally lists attachment ids to keep as evidence.
 */
export async function createDraftFromConversation(
  conversationId: string,
  attachmentIds: string[] = [],
): Promise<Ticket> {
  const response = await ensureOk(await apiFetch(
    '/api/tickets/from-conversation',
    jsonRequest({ conversation_id: conversationId, attachment_ids: attachmentIds }),
  ))
  return response.json()
}

export async function listTickets(): Promise<Ticket[]> {
  const response = await ensureOk(await apiFetch('/api/tickets'))
  return response.json()
}

export async function getTicket(ticketId: string): Promise<TicketDetail> {
  const response = await ensureOk(await apiFetch(
    `/api/tickets/${encodeURIComponent(ticketId)}`,
  ))
  return response.json()
}

export async function submitTicket(ticketId: string): Promise<Ticket> {
  const response = await ensureOk(await apiFetch(
    `/api/tickets/${encodeURIComponent(ticketId)}/submit`,
    { method: 'POST' },
  ))
  return response.json()
}

export async function updateTicketDraft(
  ticketId: string,
  payload: { title?: string; problem_summary?: string },
): Promise<Ticket> {
  const response = await ensureOk(await apiFetch(
    `/api/tickets/${encodeURIComponent(ticketId)}/draft`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ))
  return response.json()
}

export async function addTicketMessage(ticketId: string, body: string): Promise<Ticket> {
  const response = await ensureOk(await apiFetch(
    `/api/tickets/${encodeURIComponent(ticketId)}/messages`,
    jsonRequest({ body }),
  ))
  return response.json()
}

export async function confirmResolution(ticketId: string): Promise<Ticket> {
  const response = await ensureOk(await apiFetch(
    `/api/tickets/${encodeURIComponent(ticketId)}/confirm-resolution`,
    { method: 'POST' },
  ))
  return response.json()
}

export async function reopenTicket(ticketId: string): Promise<Ticket> {
  const response = await ensureOk(await apiFetch(
    `/api/tickets/${encodeURIComponent(ticketId)}/reopen`,
    { method: 'POST' },
  ))
  return response.json()
}
