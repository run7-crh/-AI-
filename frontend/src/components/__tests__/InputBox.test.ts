import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InputBox from '../InputBox.vue'
import { useChatStore } from '@/stores/chat'
import * as attachmentApi from '@/api/attachments'

vi.mock('@/api/attachments')

describe('InputBox attachments', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('offers a file picker and renders an uploaded attachment with a delete action', async () => {
    ;(attachmentApi.uploadAttachments as any).mockResolvedValue({
      attachments: [{
        id: 'att_1', original_name: 'very-long-flight-log.log', extension: 'log', size_bytes: 1024,
        status: 'ready', extraction_status: 'ready',
      }],
    })
    const wrapper = mount(InputBox)
    const store = useChatStore()
    store.currentConversationId = 'c1'
    const input = wrapper.get('input[type="file"]')
    expect(input.attributes('accept')).toContain('.pdf')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['x'], 'very-long-flight-log.log', { type: 'text/plain' })],
      configurable: true,
    })
    await input.trigger('change')
    expect(wrapper.text()).toContain('very-long-flight-log.log')
    const remove = wrapper.get('[data-testid="remove-attachment-att_1"]')
    await remove.trigger('click')
    expect(wrapper.text()).not.toContain('very-long-flight-log.log')
  })

  it('accepts image files and shows the vision privacy notice', async () => {
    ;(attachmentApi.uploadAttachments as any).mockResolvedValue({
      attachments: [{
        id: 'att_img', original_name: 'crash.png', extension: 'png', size_bytes: 2048,
        status: 'ready', extraction_status: 'ready',
      }],
    })
    const wrapper = mount(InputBox)
    const store = useChatStore()
    store.currentConversationId = 'c1'
    const input = wrapper.get('input[type="file"]')
    expect(input.attributes('accept')).toContain('.png')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['x'], 'crash.png', { type: 'image/png' })],
      configurable: true,
    })
    await input.trigger('change')
    expect(wrapper.text()).toContain('crash.png')
    expect(wrapper.find('[data-testid="vision-privacy-notice"]').exists()).toBe(true)
  })

  it('rejects images over the 8MB limit before uploading', async () => {
    const wrapper = mount(InputBox)
    const store = useChatStore()
    store.currentConversationId = 'c1'
    const big = new File([new ArrayBuffer(8 * 1024 * 1024 + 1)], 'big.png', { type: 'image/png' })
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [big], configurable: true })
    await input.trigger('change')
    expect(attachmentApi.uploadAttachments).not.toHaveBeenCalled()
    expect(store.error).toContain('8MB')
    expect(wrapper.find('[data-testid="vision-privacy-notice"]').exists()).toBe(false)
  })

  it('does not show the privacy notice for text attachments', async () => {
    ;(attachmentApi.uploadAttachments as any).mockResolvedValue({
      attachments: [{
        id: 'att_log', original_name: 'flight.log', extension: 'log', size_bytes: 1024,
        status: 'ready', extraction_status: 'ready',
      }],
    })
    const wrapper = mount(InputBox)
    const store = useChatStore()
    store.currentConversationId = 'c1'
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', {
      value: [new File(['x'], 'flight.log', { type: 'text/plain' })],
      configurable: true,
    })
    await input.trigger('change')
    expect(wrapper.find('[data-testid="vision-privacy-notice"]').exists()).toBe(false)
  })
})
