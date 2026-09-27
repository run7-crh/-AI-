import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import UserMessage from '../UserMessage.vue'
import { createPinia, setActivePinia } from 'pinia'

setActivePinia(createPinia())

describe('UserMessage attachments', () => {
  it('shows attachment summary metadata without displaying extracted text', () => {
    const wrapper = mount(UserMessage, {
      props: {
        message: {
          id: 'm1', role: 'user', content: '请帮我看日志', created_at: '',
          attachments: [{
            id: 'att_1', original_name: 'flight.log', extension: 'log', size_bytes: 2048,
            status: 'ready', extraction_status: 'ready',
          }],
        },
      },
    })
    expect(wrapper.get('[data-testid="message-attachments"]').text()).toContain('flight.log')
    expect(wrapper.text()).toContain('2 KB')
  })
})

describe('UserMessage image attachments', () => {
  it('labels image attachments as 图片 instead of the raw extension', () => {
    setActivePinia(createPinia())
    const wrapper = mount(UserMessage, {
      props: {
        message: {
          id: 'm2', role: 'user', content: '桨叶这样正常吗', created_at: '',
          attachments: [{
            id: 'att_2', original_name: 'crash.png', extension: 'png', size_bytes: 1024,
            status: 'ready', extraction_status: 'ready',
          }],
        },
      },
    })
    expect(wrapper.get('[data-testid="message-attachments"]').text()).toContain('图片 · 1 KB')
  })
})
