import type { Ticket, TicketDetail } from '@/types'
import { apiFetch } from './http'

export interface AdminTicketFilters {
  status?: string
  priority?: string
  safety_level?: string
  assignee_user_id?: string
}

export interface AdminTicketUpdate {
  status?: string
  priority?: string
  assignee_user_id?: string
  resolution_summary?: string
}

export async function listAllTickets(filters: AdminTicketFilters = {}): Promise<Ticket[]> {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  const query = params.toString()
  return (await apiFetch(`/api/admin/tickets${query ? `?${query}` : ''}`)).json()
}

export async function getTicketDetail(ticketId: string): Promise<TicketDetail> {
  return (await apiFetch(`/api/admin/tickets/${encodeURIComponent(ticketId)}`)).json()
}

export async function updateTicket(ticketId: string, payload: AdminTicketUpdate): Promise<Ticket> {
  return (await apiFetch(`/api/admin/tickets/${encodeURIComponent(ticketId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })).json()
}

export async function appendTicketEvent(
  ticketId: string,
  eventType: 'public_reply' | 'internal_note',
  body: string,
): Promise<TicketDetail> {
  return (await apiFetch(`/api/admin/tickets/${encodeURIComponent(ticketId)}/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event_type: eventType, body }),
  })).json()
}
