import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import SourceCard from '../SourceCard.vue'

describe('SourceCard', () => {
  it('opens the evidence url when source is a display title', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = mount(SourceCard, {
      props: {
        source: {
          content: '网页内容',
          source: '官方文档',
          title: '官方文档',
          url: 'https://example.com/docs',
          score: null,
        },
      },
    })

    await wrapper.trigger('click')
    expect(open).toHaveBeenCalledWith('https://example.com/docs', '_blank', 'noopener,noreferrer')
    open.mockRestore()
  })

  it('does not open unsafe URL schemes', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = mount(SourceCard, {
      props: {
        source: {
          content: '不可信来源',
          source: 'javascript:alert(1)',
          title: '不可信来源',
          url: 'javascript:alert(1)',
        },
      },
    })

    await wrapper.trigger('click')
    expect(open).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('不可信来源')
    open.mockRestore()
  })

  it('renders evidence metadata and degrades when optional fields are absent', () => {
    const wrapper = mount(SourceCard, {
      props: {
        source: {
          content: '故障排查内容',
          source: 'drone_troubleshooting.md',
          title: '电池排查',
          source_type: 'local',
          document_type: 'safety',
          product_model: 'mini_4_pro',
          component: 'battery',
          fault_type: 'battery_swelling',
          data_type: 'synthetic',
          document_id: 'doc-1',
          source_id: 'SOURCE-1',
          score: 0.876,
        },
      },
    })

    expect(wrapper.get('[data-testid="source-metadata"]').text()).toContain('模拟案例')
    expect(wrapper.text()).toContain('安全资料')
    expect(wrapper.text()).toContain('mini_4_pro')
    expect(wrapper.text()).toContain('0.876')
  })

  it('keeps legacy sources renderable without new metadata', () => {
    const wrapper = mount(SourceCard, {
      props: { source: { content: '旧来源', source: 'legacy.md', title: '旧资料' } },
    })

    expect(wrapper.text()).toContain('旧资料')
    expect(wrapper.find('[data-testid="source-metadata"]').exists()).toBe(false)
  })

  it('labels user-upload evidence without treating it as knowledge-base material', () => {
    const wrapper = mount(SourceCard, {
      props: {
        source: {
          content: '附件正文仅用于当前轮，未持久化',
          source: '用户附件：flight.log',
          title: 'flight.log',
          source_type: 'attachment',
          data_type: 'user_upload',
          document_type: 'attachment',
          document_id: 'attachment:att_1',
          source_id: 'ATTACHMENT:att_1',
          score: null,
        },
      },
    })

    expect(wrapper.get('[data-testid="source-metadata"]').text()).toContain('用户附件')
    expect(wrapper.text()).not.toContain('知识库资料')
  })
})

describe('SourceCard image observations', () => {
  it('renders image observation label and content from media_type evidence', () => {
    const wrapper = mount(SourceCard, {
      props: {
        source: {
          content: '[图片类型] 实物照片\n[可见异常] 桨叶末端缺口',
          source: '用户附件：crash.png',
          title: 'crash.png',
          source_type: 'attachment',
          data_type: 'user_upload',
          media_type: 'image',
          score: null,
        },
      },
    })
    expect(wrapper.text()).toContain('图片观察')
    expect(wrapper.text()).toContain('桨叶末端缺口')
    expect(wrapper.text()).not.toContain('附件正文仅用于当前轮')
  })

  it('keeps the text attachment label when media_type is absent', () => {
    const wrapper = mount(SourceCard, {
      props: {
        source: {
          content: '附件正文仅用于当前轮，未持久化',
          source: '用户附件：flight.log',
          title: 'flight.log',
          source_type: 'attachment',
          data_type: 'user_upload',
          score: null,
        },
      },
    })
    expect(wrapper.text()).toContain('用户附件')
    expect(wrapper.text()).not.toContain('图片观察')
  })
})
