import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TicketTimeline from '../TicketTimeline.vue'
import type { TicketEvent } from '@/types'

function event(overrides: Partial<TicketEvent>): TicketEvent {
  return {
    id: 'e1', ticket_id: 't1', actor_type: 'admin', actor_id: 'a1',
    event_type: 'assigned', from_status: 'submitted', to_status: 'assigned',
    body: null, metadata: {}, created_at: '2026-09-25T00:00:00Z',
    ...overrides,
  }
}

describe('TicketTimeline', () => {
  it('renders public events with labels and actor names', () => {
    const wrapper = mount(TicketTimeline, {
      props: {
        events: [
          event({ id: 'e1', event_type: 'created', actor_type: 'user', actor_id: 'u1' }),
          event({ id: 'e2', event_type: 'public_reply', body: '请先升级固件。' }),
        ],
      },
    })

    expect(wrapper.text()).toContain('创建工单草稿')
    expect(wrapper.text()).toContain('客服回复')
    expect(wrapper.text()).toContain('请先升级固件。')
    expect(wrapper.text()).toContain('客服')
  })

  it('never renders internal notes even if the backend omits its filter', () => {
    const wrapper = mount(TicketTimeline, {
      props: {
        events: [
          event({ id: 'e1', event_type: 'assigned' }),
          event({ id: 'e2', event_type: 'internal_note', body: '内部判断：疑似硬件故障。' }),
        ],
      },
    })

    expect(wrapper.text()).not.toContain('内部判断')
    expect(wrapper.text()).not.toContain('internal_note')
  })

  it('shows an empty hint when there are no visible events', () => {
    const wrapper = mount(TicketTimeline, { props: { events: [] } })
    expect(wrapper.text()).toContain('暂无处理记录')
  })
})
