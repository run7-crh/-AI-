import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import ConversationTicketPanel from '../ConversationTicketPanel.vue'
import { useTicketsStore } from '@/stores/tickets'

vi.mock('@/stores/tickets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/stores/tickets')>()
  return actual
})

describe('ConversationTicketPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('hides entirely when there is no conversation yet', () => {
    const wrapper = mount(ConversationTicketPanel, { props: { conversationId: null } })
    expect(wrapper.find('[data-testid="conversation-ticket-panel"]').exists()).toBe(false)
  })

  it('opens the draft card on demand and closes it again', async () => {
    const wrapper = mount(ConversationTicketPanel, { props: { conversationId: 'c1' } })

    expect(wrapper.find('[data-testid="ticket-draft-card"]').exists()).toBe(false)
    await wrapper.find('[data-testid="toggle-ticket-panel"]').trigger('click')
    expect(wrapper.find('[data-testid="ticket-draft-card"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('收起工单')

    await wrapper.find('[data-testid="toggle-ticket-panel"]').trigger('click')
    expect(wrapper.find('[data-testid="ticket-draft-card"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('就此会话生成售后工单')
  })

  it('passes the current conversation id to the draft card', async () => {
    const wrapper = mount(ConversationTicketPanel, { props: { conversationId: 'conv-42' } })
    await wrapper.find('[data-testid="toggle-ticket-panel"]').trigger('click')

    const store = useTicketsStore()
    const createDraft = vi.spyOn(store, 'createDraft').mockResolvedValue({
      id: 't1', ticket_number: 'T-1', user_id: 'u1', conversation_id: 'conv-42',
      title: 't', problem_summary: 's', device_model: null, serial_number: null,
      firmware_version: null, fault_category: null, priority: 'normal' as const,
      safety_level: 'none', escalation_reason: null, assignee_user_id: null,
      status: 'draft' as const, resolution_summary: null,
      created_at: '', updated_at: '', resolved_at: null, closed_at: null,
      user_confirmed_at: null,
    })
    await wrapper.find('[data-testid="create-draft-button"]').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(createDraft).toHaveBeenCalledWith('conv-42')
  })
})
