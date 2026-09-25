import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import TicketDraftCard from '../TicketDraftCard.vue'
import { useTicketsStore } from '@/stores/tickets'

vi.mock('@/stores/tickets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/stores/tickets')>()
  return actual
})

const draftTicket = {
  id: 't1', ticket_number: 'T-20260925-AAAA01', user_id: 'u1', conversation_id: 'c1',
  title: '罗盘异常', problem_summary: '用户问题：罗盘异常', device_model: null,
  serial_number: null, firmware_version: null, fault_category: null,
  priority: 'normal' as const, safety_level: 'none', escalation_reason: null,
  assignee_user_id: null, status: 'draft' as const, resolution_summary: null,
  created_at: '2026-09-25T00:00:00Z', updated_at: '2026-09-25T00:00:00Z',
  resolved_at: null, closed_at: null, user_confirmed_at: null,
}

describe('TicketDraftCard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('creates a draft on demand and shows the server snapshot before submitting', async () => {
    const wrapper = mount(TicketDraftCard, { props: { conversationId: 'c1' } })
    const store = useTicketsStore()
    const createDraft = vi.spyOn(store, 'createDraft').mockResolvedValue(draftTicket)

    await wrapper.find('[data-testid="create-draft-button"]').trigger('click')
    await vi.dynamicImportSettled?.()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(createDraft).toHaveBeenCalledWith('c1')
    expect(wrapper.find('[data-testid="draft-number"]').text()).toBe('T-20260925-AAAA01')
    expect(wrapper.text()).toContain('用户问题：罗盘异常')
    expect(wrapper.find('[data-testid="submit-draft-button"]').exists()).toBe(true)
    expect(wrapper.emitted('created')).toBeTruthy()
  })

  it('submits the confirmed draft and reports completion', async () => {
    const wrapper = mount(TicketDraftCard, { props: { conversationId: 'c1' } })
    const store = useTicketsStore()
    vi.spyOn(store, 'createDraft').mockResolvedValue(draftTicket)
    vi.spyOn(store, 'submit').mockResolvedValue({ ...draftTicket, status: 'submitted' })

    await wrapper.find('[data-testid="create-draft-button"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))
    await wrapper.find('[data-testid="submit-draft-button"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(wrapper.find('[data-testid="draft-submitted"]').exists()).toBe(true)
    expect(wrapper.emitted('submitted')).toBeTruthy()
  })

  it('surfaces store errors when draft creation fails', async () => {
    const wrapper = mount(TicketDraftCard, { props: { conversationId: 'c1' } })
    const store = useTicketsStore()
    store.error = '创建工单失败'
    vi.spyOn(store, 'createDraft').mockRejectedValue(new Error('conversation_not_found'))

    await wrapper.find('[data-testid="create-draft-button"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(wrapper.find('[data-testid="draft-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('创建工单失败')
  })
})
