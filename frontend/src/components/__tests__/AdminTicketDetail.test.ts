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

  it('renders an assignee dropdown when user options are provided', async () => {
    ;(adminTicketsApi.updateTicket as any).mockResolvedValue({ ...ticket, assignee_user_id: 'admin-9' })
    const wrapper = mount(AdminTicketDetail, {
      props: {
        ticketId: 't1',
        isAdmin: true,
        assigneeOptions: [
          { id: 'admin-9', username: 'brand-admin', role: 'admin', is_active: true, created_at: '' },
          { id: 'u2', username: 'cxh', role: 'user', is_active: true, created_at: '' },
        ],
      },
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="assignee-select"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="assignee-input"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('brand-admin')

    await wrapper.find('[data-testid="assignee-select"]').setValue('admin-9')
    await wrapper.find('[data-testid="assign-button"]').trigger('click')
    await flushPromises()
    expect(adminTicketsApi.updateTicket).toHaveBeenCalledWith('t1', { assignee_user_id: 'admin-9' })
  })

  it('keeps the manual assignee input when no user options are given', async () => {
    const wrapper = mount(AdminTicketDetail, { props: { ticketId: 't1', isAdmin: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="assignee-select"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="assignee-input"]').exists()).toBe(true)
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

  it('renders the latest AI analysis from agent_suggestion metadata', async () => {
    ;(adminTicketsApi.getTicketDetail as any).mockResolvedValue(detail({
      events: [
        event({
          id: 'e9',
          actor_type: 'agent',
          event_type: 'agent_suggestion',
          body: '疑似固件问题',
          metadata: {
            summary: '疑似固件问题',
            product_model: 'mini_4_pro',
            fault_category: 'transmission_abnormal',
            confidence: 0.72,
            diagnosis: {
              summary: '疑似固件问题',
              possible_causes: [{ cause: '固件异常', status: 'knowledge_based' }],
              safety_warning: '操作前取出电池',
            },
            knowledge: [{ id: 'k1', source: 'troubleshooting/firmware.md', data_type: 'factual', score: 0.82 }],
            sop_recommendations: [{ id: 'k2', source: 'sop/firmware_upgrade.md' }],
            handling_advice: ['先远程指导检查固件', '无效则安排检测'],
            suggested_reply: '您好，建议先重启并检查固件版本。',
            risk_flags: [],
            high_risk: false,
            disclaimers: ['AI 分析仅供参考，最终处理以人工确认为准'],
          },
        }),
      ],
    }))
    const wrapper = mount(AdminTicketDetail, { props: { ticketId: 't1', isAdmin: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="ai-analysis-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="ai-summary"]').text()).toContain('疑似固件问题')
    expect(wrapper.find('[data-testid="ai-causes"]').text()).toContain('知识库明确')
    expect(wrapper.find('[data-testid="ai-knowledge"]').text()).toContain('troubleshooting/firmware.md')
    expect(wrapper.find('[data-testid="ai-sop"]').text()).toContain('sop/firmware_upgrade.md')
    expect(wrapper.find('[data-testid="ai-advice"]').text()).toContain('无效则安排检测')
    expect(wrapper.find('[data-testid="ai-safety"]').text()).toContain('取出电池')
    expect(wrapper.find('[data-testid="ai-suggested-reply"]').text()).toContain('重启并检查固件')
    expect(wrapper.find('[data-testid="ai-high-risk"]').exists()).toBe(false)
  })

  it('prefills the public reply box on adopt without auto-sending', async () => {
    ;(adminTicketsApi.getTicketDetail as any).mockResolvedValue(detail({
      events: [
        event({
          id: 'e9', actor_type: 'agent', event_type: 'agent_suggestion',
          body: '摘要',
          metadata: { summary: '摘要', suggested_reply: '您好，建议先重启。', handling_advice: ['x'] },
        }),
      ],
    }))
    const wrapper = mount(AdminTicketDetail, { props: { ticketId: 't1', isAdmin: true } })
    await flushPromises()

    await wrapper.find('[data-testid="adopt-suggestion"]').trigger('click')
    expect((wrapper.find('[data-testid="event-body"]').element as HTMLInputElement).value).toBe('您好，建议先重启。')
    expect((wrapper.find('[data-testid="event-type"]').element as HTMLSelectElement).value).toBe('public_reply')
    // 采用 = 仅预填，绝不自动发送
    expect(adminTicketsApi.appendTicketEvent).not.toHaveBeenCalled()
  })

  it('re-analysis calls the AI endpoint and keeps high-risk banner', async () => {
    ;(adminTicketsApi.analyzeTicketWithAI as any).mockResolvedValue({
      summary: '高风险：电池鼓包',
      suggested_reply: '请立即停止充电并隔离电池。',
      handling_advice: ['按保守清单处理'],
      high_risk: true,
      risk_flags: ['ticket_safety_level_high'],
    })
    const wrapper = mount(AdminTicketDetail, { props: { ticketId: 't1', isAdmin: true } })
    await flushPromises()

    expect(wrapper.find('[data-testid="ai-analysis-panel"]').exists()).toBe(true)
    await wrapper.find('[data-testid="run-analysis"]').trigger('click')
    await flushPromises()

    expect(adminTicketsApi.analyzeTicketWithAI).toHaveBeenCalledWith('t1')
    expect(wrapper.find('[data-testid="ai-high-risk"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="ai-suggested-reply"]').text()).toContain('停止充电')
  })
})
