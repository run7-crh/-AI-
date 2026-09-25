import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminTicketDetail from '../AdminTicketDetail.vue'
import * as adminTicketsApi from '@/api/adminTickets'

vi.mock('@/api/adminTickets')

const ticket = {
  id: 't1', ticket_number: 'T-20260925-AAAA01', user_id: 'u1', conversation_id: 'c1',
  title: '罗盘异常', problem_summary: '用户问题：罗盘异常', device_model: 'mini_4_pro',
  serial_number: null, firmware_version: null, fault_category: 'compass_abnormal',
  priority: 'normal' as const, safety_level: 'high', escalation_reason: '高风险',
  assignee_user_id: null, status: 'submitted' as const, resolution_summary: null,
  created_at: '2026-09-25T00:00:00Z', updated_at: '2026-09-25T00:00:00Z',
  resolved_at: null, closed_at: null, user_confirmed_at: null,
}

function event(overrides: Record<string, unknown>) {
  return {
    id: 'e1', ticket_id: 't1', actor_type: 'admin', actor_id: 'a1',
    event_type: 'assigned', from_status: null, to_status: null,
    body: null, metadata: {}, created_at: '2026-09-25T00:00:00Z',
    ...overrides,
  }
}

function detail(overrides: { ticket?: Partial<typeof ticket>; events?: Array<Record<string, unknown>> } = {}) {
  return {
    ticket: { ...ticket, ...(overrides.ticket || {}) },
    events: overrides.events || [],
    evidence: [],
  }
}

describe('AdminTicketDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(adminTicketsApi.getTicketDetail as any).mockResolvedValue(detail({
      events: [
        event({ id: 'e1', event_type: 'assigned', to_status: 'assigned' }),
        event({ id: 'e2', actor_type: 'agent', event_type: 'agent_suggestion', body: '建议优先检查固件版本。' }),
        event({ id: 'e3', event_type: 'public_reply', body: '请先升级固件。' }),
        event({ id: 'e4', event_type: 'internal_note', body: '内部判断：疑似硬件老化。' }),
      ],
    }))
  })

  it('distinguishes agent suggestions, public replies and internal notes', async () => {
    const wrapper = mount(AdminTicketDetail, { props: { ticketId: 't1', isAdmin: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="event-agent_suggestion"]').classes()).toContain('bg-indigo-50')
    expect(wrapper.find('[data-testid="event-public_reply"]').classes()).toContain('bg-white')
    expect(wrapper.find('[data-testid="event-internal_note"]').classes()).toContain('bg-amber-50')
    expect(wrapper.text()).toContain('AI 建议')
    expect(wrapper.text()).toContain('客服回复')
    expect(wrapper.text()).toContain('内部备注')
  })

  it('hides admin actions for non-admin rendering', async () => {
    const wrapper = mount(AdminTicketDetail, { props: { ticketId: 't1', isAdmin: false } })
    await flushPromises()

    expect(wrapper.find('[data-testid="admin-actions"]').exists()).toBe(false)
  })

  it('enables only whitelisted transition buttons for the current status', async () => {
    const wrapper = mount(AdminTicketDetail, { props: { ticketId: 't1', isAdmin: true } })
    await flushPromises()

    const allowed = wrapper.find('[data-testid="status-button-assigned"]')
    const disallowed = wrapper.find('[data-testid="status-button-closed"]')
    expect(allowed.exists()).toBe(true)
    expect(allowed.attributes('disabled')).toBeUndefined()
    expect(disallowed.exists()).toBe(true)
    expect(disallowed.attributes('disabled')).toBeDefined()
  })

  it('sends status, assignee and event updates through the admin API', async () => {
    ;(adminTicketsApi.updateTicket as any).mockResolvedValue({ ...ticket, status: 'assigned' })
    ;(adminTicketsApi.appendTicketEvent as any).mockResolvedValue(detail())
    const wrapper = mount(AdminTicketDetail, { props: { ticketId: 't1', isAdmin: true } })
    await flushPromises()

    await wrapper.find('[data-testid="status-button-assigned"]').trigger('click')
    await flushPromises()
    expect(adminTicketsApi.updateTicket).toHaveBeenCalledWith('t1', { status: 'assigned' })

    await wrapper.find('[data-testid="assignee-input"]').setValue('admin-9')
    await wrapper.find('[data-testid="assign-button"]').trigger('click')
    await flushPromises()
    expect(adminTicketsApi.updateTicket).toHaveBeenCalledWith('t1', { assignee_user_id: 'admin-9' })

    await wrapper.find('[data-testid="event-type"]').setValue('internal_note')
    await wrapper.find('[data-testid="event-body"]').setValue('内部判断：疑似硬件老化。')
    await wrapper.find('[data-testid="send-event"]').trigger('click')
    await flushPromises()
    expect(adminTicketsApi.appendTicketEvent).toHaveBeenCalledWith('t1', 'internal_note', '内部判断：疑似硬件老化。')
  })
})
