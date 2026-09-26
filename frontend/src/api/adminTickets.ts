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

// 阶段 6：管理端 AI 售后分析（结构由后端 TicketAnalysisService 产出）
export interface AgentAnalysisKnowledge {
  id?: string
  title?: string
  source?: string
  document_type?: string | null
  product_model?: string | null
  fault_type?: string | null
  data_type?: string | null
  score?: number | null
}

export interface AgentSuggestion {
  ticket_id: string
  ticket_number?: string
  summary?: string
  product_model?: string | null
  fault_category?: string | null
  diagnosis?: {
    summary?: string
    possible_causes?: { cause?: string; status?: string; evidence_ids?: string[] }[]
    recommended_steps?: { step?: string; expected?: string; stop_condition?: string }[]
    safety_warning?: string | null
    confidence?: number
    citations?: { evidence_id?: string; document_name?: string; data_type?: string | null }[]
  } | null
  knowledge?: AgentAnalysisKnowledge[]
  sop_recommendations?: AgentAnalysisKnowledge[]
  handling_advice?: string[]
  suggested_reply?: string
  risk_flags?: string[]
  high_risk?: boolean
  confidence?: number
  profile_source?: string
  model?: string
  analyzed_at?: string
  disclaimers?: string[]
}

export async function analyzeTicketWithAI(ticketId: string): Promise<AgentSuggestion> {
  return (await apiFetch(
    `/api/admin/tickets/${encodeURIComponent(ticketId)}/ai-analysis`,
    { method: 'POST' },
  )).json()
}
