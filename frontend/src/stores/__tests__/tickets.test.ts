import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTicketsStore } from '../tickets'
import * as ticketsApi from '@/api/tickets'

vi.mock('@/api/tickets')

const draftTicket = {
  id: 't1', ticket_number: 'T-20260925-AAAA01', user_id: 'u1', conversation_id: 'c1',
  title: '罗盘异常', problem_summary: '用户问题：罗盘异常', device_model: 'mini_4_pro',
  serial_number: null, firmware_version: null, fault_category: 'compass_abnormal',
  priority: 'normal' as const, safety_level: 'none', escalation_reason: null,
  assignee_user_id: null, status: 'draft' as const, resolution_summary: null,
  created_at: '2026-09-25T00:00:00Z', updated_at: '2026-09-25T00:00:00Z',
  resolved_at: null, closed_at: null, user_confirmed_at: null,
}

const submittedTicket = { ...draftTicket, status: 'submitted' as const }
const closedTicket = {
  ...draftTicket,
  status: 'closed' as const,
  user_confirmed_at: '2026-09-25T01:00:00Z',
}

describe('tickets store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loads tickets into the list', async () => {
    ;(ticketsApi.listTickets as any).mockResolvedValue([draftTicket])
    const store = useTicketsStore()

    await store.loadTickets()

    expect(store.tickets).toHaveLength(1)
    expect(store.error).toBeNull()
  })

  it('creates a draft, keeps it in the list, and submits it in place', async () => {
    ;(ticketsApi.createDraftFromConversation as any).mockResolvedValue(draftTicket)
    ;(ticketsApi.submitTicket as any).mockResolvedValue(submittedTicket)
    const store = useTicketsStore()

    const created = await store.createDraft('c1', ['att_1'])
    expect(created.id).toBe('t1')
    expect(ticketsApi.createDraftFromConversation).toHaveBeenCalledWith('c1', ['att_1'])
    expect(store.tickets).toHaveLength(1)

    const submitted = await store.submit('t1')
    expect(submitted.status).toBe('submitted')
    expect(store.tickets[0].status).toBe('submitted')
  })

  it('opens detail and refreshes it when the ticket is reopened', async () => {
    const detail = {
      ticket: draftTicket,
      events: [{ id: 'e1', ticket_id: 't1', actor_type: 'user', actor_id: 'u1', event_type: 'created', from_status: null, to_status: 'draft', body: null, metadata: {}, created_at: '2026-09-25T00:00:00Z' }],
      evidence: [],
    }
    ;(ticketsApi.getTicket as any).mockResolvedValueOnce(detail).mockResolvedValueOnce({
      ...detail,
      ticket: { ...draftTicket, status: 'reopened' },
    })
    ;(ticketsApi.reopenTicket as any).mockResolvedValue({ ...draftTicket, status: 'reopened' })
    const store = useTicketsStore()

    await store.openDetail('t1')
    expect(store.currentTicket?.id).toBe('t1')
    expect(store.current?.events).toHaveLength(1)

    await store.reopen('t1')
    expect(store.currentTicket?.status).toBe('reopened')
    expect(ticketsApi.getTicket).toHaveBeenCalledTimes(2)
  })

  it('records errors from failed actions and keeps the store usable', async () => {
    ;(ticketsApi.createDraftFromConversation as any).mockRejectedValue(new Error('conversation_not_found'))
    const store = useTicketsStore()

    await expect(store.createDraft('bad-conv')).rejects.toThrow('conversation_not_found')
    expect(store.error).toBe('conversation_not_found')
    expect(store.tickets).toHaveLength(0)
  })

  it('sends supplementary messages and reloads the detail timeline', async () => {
    ;(ticketsApi.getTicket as any).mockResolvedValue({
      ticket: closedTicket,
      events: [],
      evidence: [],
    })
    ;(ticketsApi.addTicketMessage as any).mockResolvedValue(closedTicket)
    const store = useTicketsStore()

    await store.openDetail('t1')
    await store.addMessage('t1', '已经按步骤处理，问题解决了。')

    expect(ticketsApi.addTicketMessage).toHaveBeenCalledWith('t1', '已经按步骤处理，问题解决了。')
    expect(ticketsApi.getTicket).toHaveBeenCalledTimes(2)
  })
})
