import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import TicketDraftModal from '../TicketDraftModal.vue'

describe('TicketDraftModal', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.body.innerHTML = ''
  })

  function mountModal(props: { open: boolean; conversationId: string | null }) {
    return mount(TicketDraftModal, { props })
  }

  it('renders nothing when closed', () => {
    mountModal({ open: false, conversationId: 'c1' })
    expect(document.body.querySelector('[data-testid="ticket-draft-modal"]')).toBeNull()
  })

  it('teleports the dialog with the draft card to the document body', () => {
    mountModal({ open: true, conversationId: 'c1' })

    const modal = document.body.querySelector('[data-testid="ticket-draft-modal"]')
    expect(modal).not.toBeNull()
    expect(modal?.getAttribute('role')).toBe('dialog')
    expect(document.body.querySelector('[data-testid="ticket-draft-card"]')).not.toBeNull()
    expect(document.body.textContent).toContain('生成售后工单')
  })

  it('shows a hint instead of the card when there is no conversation', () => {
    mountModal({ open: true, conversationId: null })

    expect(document.body.querySelector('[data-testid="ticket-draft-card"]')).toBeNull()
    expect(document.body.textContent).toContain('先在聊天中发起对话')
  })

  it('closes via the close button, backdrop click and the Escape key', async () => {
    const wrapper = mountModal({ open: true, conversationId: 'c1' })

    ;(document.body.querySelector('[data-testid="modal-close"]') as HTMLButtonElement).click()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.emitted('close')).toHaveLength(1)

    ;(document.body.querySelector('[data-testid="modal-backdrop"]') as HTMLDivElement).click()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.emitted('close')).toHaveLength(2)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(wrapper.emitted('close')).toHaveLength(3)
  })

  it('ignores Escape when the modal is closed', () => {
    const wrapper = mountModal({ open: false, conversationId: 'c1' })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(wrapper.emitted('close')).toBeUndefined()
  })
})
