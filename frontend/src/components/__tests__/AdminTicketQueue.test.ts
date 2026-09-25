import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AdminTicketQueue from '../AdminTicketQueue.vue'
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

describe('AdminTicketQueue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(adminTicketsApi.listAllTickets as any).mockResolvedValue([ticket])
  })

  it('loads the queue on mount', async () => {
    const wrapper = mount(AdminTicketQueue)
    await flushPromises()

    expect(adminTicketsApi.listAllTickets).toHaveBeenCalledWith({})
    expect(wrapper.text()).toContain('T-20260925-AAAA01')
    expect(wrapper.text()).toContain('罗盘异常')
  })

  it('re-requests the list with cumulative filter params', async () => {
    const wrapper = mount(AdminTicketQueue)
    await flushPromises()

    await wrapper.find('[data-testid="filter-status"]').setValue('assigned')
    expect(adminTicketsApi.listAllTickets).toHaveBeenLastCalledWith({ status: 'assigned' })

    await wrapper.find('[data-testid="filter-priority"]').setValue('high')
    expect(adminTicketsApi.listAllTickets).toHaveBeenLastCalledWith({ status: 'assigned', priority: 'high' })

    await wrapper.find('[data-testid="filter-safety"]').setValue('high')
    expect(adminTicketsApi.listAllTickets).toHaveBeenLastCalledWith({
      status: 'assigned',
      priority: 'high',
      safety_level: 'high',
    })

    await wrapper.find('[data-testid="filter-assignee"]').setValue('admin-1')
    await wrapper.find('[data-testid="filter-assignee"]').trigger('keydown.enter')
    expect(adminTicketsApi.listAllTickets).toHaveBeenLastCalledWith({
      status: 'assigned',
      priority: 'high',
      safety_level: 'high',
      assignee_user_id: 'admin-1',
    })
  })

  it('opens the detail view when a row is selected', async () => {
    ;(adminTicketsApi.getTicketDetail as any).mockResolvedValue({ ticket, events: [], evidence: [] })
    const wrapper = mount(AdminTicketQueue, {
      props: {
        users: [
          { id: 'admin-1', username: 'brand-admin', role: 'admin', is_active: true, created_at: '' },
        ],
      },
    })
    await flushPromises()

    await wrapper.find('[data-testid="admin-ticket-row-T-20260925-AAAA01"]').trigger('click')
    await flushPromises()

    expect(adminTicketsApi.getTicketDetail).toHaveBeenCalledWith('t1')
    expect(wrapper.find('[data-testid="admin-ticket-detail"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="assignee-select"]').exists()).toBe(true)
  })
})
