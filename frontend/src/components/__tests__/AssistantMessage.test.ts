import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AssistantMessage from '../AssistantMessage.vue'

setActivePinia(createPinia())

const global = {
  stubs: {
    MarkdownRenderer: { template: '<div>{{ content }}</div>', props: ['content'] },
    TraceTimeline: { template: '<div />' },
    JudgeBadges: { template: '<div />' },
  },
}

function message(overrides: Record<string, unknown> = {}) {
  return {
    id: 'm1',
    role: 'assistant' as const,
    content: '回答内容',
    created_at: '',
    ...overrides,
  }
}

describe('AssistantMessage after-sales notices', () => {
  it('shows the backend safety result and escalation guidance', () => {
    const wrapper = mount(AssistantMessage, {
      props: { message: message({ safety_flag: true, safety_level: 'high', safety_situation: 'charging', escalation_required: true }) },
      global,
    })

    expect(wrapper.get('[data-testid="safety-notice"]').text()).toContain('高风险')
    expect(wrapper.text()).toContain('充电中')
    expect(wrapper.text()).toContain('建议联系人工')
  })

  it('shows standalone escalation guidance and optional intent', () => {
    const wrapper = mount(AssistantMessage, {
      props: { message: message({ escalation_required: true, intent: 'troubleshooting' }) },
      global,
    })

    expect(wrapper.find('[data-testid="escalation-notice"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="intent-label"]').text()).toContain('故障排查')
  })

  it('keeps legacy messages without safety fields unchanged', () => {
    const wrapper = mount(AssistantMessage, { props: { message: message() }, global })

    expect(wrapper.find('[data-testid="safety-notice"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="escalation-notice"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('回答内容')
  })

  it('shows agent ticket draft notice only when decision is create_ticket', () => {
    // 阶段 5：Agent 已建草稿 → 显示提示与查看按钮（不自动提交）
    const wrapper = mount(AssistantMessage, {
      props: {
        message: message({
          recommended_action: 'create_ticket',
          agent_ticket: { id: 't1', ticket_number: 'T-001', status: 'draft' },
        }),
      },
      global,
    })
    const notice = wrapper.find('[data-testid="agent-ticket-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('T-001')
    expect(notice.text()).toContain('待你确认提交')
    expect(wrapper.find('[data-testid="view-agent-ticket"]').exists()).toBe(true)
  })

  it('hides agent ticket notice when no ticket was created', () => {
    const wrapper = mount(AssistantMessage, {
      props: { message: message({ recommended_action: 'answer' }) },
      global,
    })
    expect(wrapper.find('[data-testid="agent-ticket-notice"]').exists()).toBe(false)
  })

  it('shows attachment processing status and user attachment evidence', () => {
    const wrapper = mount(AssistantMessage, {
      props: {
        message: message({
          attachment_status: { phase: 'parse', status: 'ready', attachment_ids: ['att_1'] },
          sources: [{
            content: '附件正文仅用于当前轮，未持久化',
            source: '用户附件：flight.log',
            title: 'flight.log',
            source_type: 'attachment',
            data_type: 'user_upload',
            document_type: 'attachment',
            document_id: 'attachment:att_1',
            source_id: 'ATTACHMENT:att_1',
            score: null,
          }],
        }),
        global,
      },
    })

    expect(wrapper.get('[data-testid="attachment-status"]').text()).toContain('附件已解析')
    expect(wrapper.text()).toContain('用户附件')
  })
})
