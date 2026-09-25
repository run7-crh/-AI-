import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import ConversationTicketPanel from '../ConversationTicketPanel.vue'
import { useTicketsStore } from '@/stores/tickets'

vi.mock('@/stores/tickets', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/stores/tickets')>()
  return actual
})

const draftTicket = {
  id: 't1', ticket_number: 'T-1', user_id: 'u1', conversation_id: 'conv-42',
  title: 't', problem_summary: 's', device_model: null, serial_number: null,
  firmware_version: null, fault_category: null, priority: 'normal' as const,
  safety_level: 'none', escalation_reason: null, assignee_user_id: null,
  status: 'draft' as const, resolution_summary: null,
  created_at: '', updated_at: '', resolved_at: null, closed_at: null,
  user_confirmed_at: null,
}

describe('ConversationTicketPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.body.innerHTML = ''
  })

  it('hides entirely when there is no conversation yet', () => {
    const wrapper = mount(ConversationTicketPanel, { props: { conversationId: null } })
    expect(wrapper.find('[data-testid="conversation-ticket-panel"]').exists()).toBe(false)
  })

  it('opens the draft modal on demand', async () => {
    const wrapper = mount(ConversationTicketPanel, { props: { conversationId: 'c1' } })

    expect(document.body.querySelector('[data-testid="ticket-draft-modal"]')).toBeNull()
    await wrapper.find('[data-testid="toggle-ticket-panel"]').trigger('click')
    expect(document.body.querySelector('[data-testid="ticket-draft-modal"]')).not.toBeNull()
    expect(document.body.querySelector('[data-testid="ticket-draft-card"]')).not.toBeNull()
  })

  it('passes the current conversation id to the draft card', async () => {
    const wrapper = mount(ConversationTicketPanel, { props: { conversationId: 'conv-42' } })
    await wrapper.find('[data-testid="toggle-ticket-panel"]').trigger('click')

    const store = useTicketsStore()
    const createDraft = vi.spyOn(store, 'createDraft').mockResolvedValue(draftTicket)
    const cardButton = document.body.querySelector('[data-testid="create-draft-button"]') as HTMLButtonElement
    cardButton.click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(createDraft).toHaveBeenCalledWith('conv-42')
  })
})
