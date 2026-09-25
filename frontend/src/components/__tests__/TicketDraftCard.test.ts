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
  title: '无人机机翼被砸断了可以换新吗？', problem_summary: '用户问题：机翼被砸断\n初步建议：请联系官方售后',
  device_model: null,
  serial_number: null, firmware_version: null, fault_category: null,
  priority: 'normal' as const, safety_level: 'none', escalation_reason: null,
  assignee_user_id: null, status: 'draft' as const, resolution_summary: null,
  created_at: '2026-09-25T00:00:00Z', updated_at: '2026-09-25T00:00:00Z',
  resolved_at: null, closed_at: null, user_confirmed_at: null,
}

async function settle(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('TicketDraftCard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('creates a draft and shows the server snapshot in editable fields', async () => {
    const wrapper = mount(TicketDraftCard, { props: { conversationId: 'c1' } })
    const store = useTicketsStore()
    const createDraft = vi.spyOn(store, 'createDraft').mockResolvedValue(draftTicket)

    await wrapper.find('[data-testid="create-draft-button"]').trigger('click')
    await settle()

    expect(createDraft).toHaveBeenCalledWith('c1')
    expect(wrapper.find('[data-testid="draft-number"]').text()).toBe('T-20260925-AAAA01')
    const titleInput = wrapper.find('[data-testid="draft-title-input"]')
    const summaryInput = wrapper.find('[data-testid="draft-summary-input"]')
    expect((titleInput.element as HTMLInputElement).value).toBe(draftTicket.title)
    expect((summaryInput.element as HTMLTextAreaElement).value).toBe(draftTicket.problem_summary)
    expect(wrapper.text()).toContain('安全等级由系统判定')
    expect(wrapper.emitted('created')).toBeTruthy()
  })

  it('patches the edited title and summary before submitting', async () => {
    const wrapper = mount(TicketDraftCard, { props: { conversationId: 'c1' } })
    const store = useTicketsStore()
    vi.spyOn(store, 'createDraft').mockResolvedValue(draftTicket)
    const updateDraft = vi.spyOn(store, 'updateDraft').mockResolvedValue({
      ...draftTicket,
      title: '机翼断裂更换咨询',
      problem_summary: '仓库中被砸断机翼，咨询更换流程。',
    })
    const submit = vi.spyOn(store, 'submit').mockResolvedValue({
      ...draftTicket,
      status: 'submitted',
    })

    await wrapper.find('[data-testid="create-draft-button"]').trigger('click')
    await settle()
    await wrapper.find('[data-testid="draft-title-input"]').setValue('机翼断裂更换咨询')
    await wrapper.find('[data-testid="draft-summary-input"]').setValue('仓库中被砸断机翼，咨询更换流程。')
    await wrapper.find('[data-testid="submit-draft-button"]').trigger('click')
    await settle()

    expect(updateDraft).toHaveBeenCalledWith('t1', {
      title: '机翼断裂更换咨询',
      problem_summary: '仓库中被砸断机翼，咨询更换流程。',
    })
    expect(submit).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="draft-submitted"]').exists()).toBe(true)
    expect(wrapper.emitted('submitted')).toBeTruthy()
  })

  it('submits directly without patching when fields are untouched', async () => {
    const wrapper = mount(TicketDraftCard, { props: { conversationId: 'c1' } })
    const store = useTicketsStore()
    vi.spyOn(store, 'createDraft').mockResolvedValue(draftTicket)
    const updateDraft = vi.spyOn(store, 'updateDraft')
    const submit = vi.spyOn(store, 'submit').mockResolvedValue({
      ...draftTicket,
      status: 'submitted',
    })

    await wrapper.find('[data-testid="create-draft-button"]').trigger('click')
    await settle()
    await wrapper.find('[data-testid="submit-draft-button"]').trigger('click')
    await settle()

    expect(updateDraft).not.toHaveBeenCalled()
    expect(submit).toHaveBeenCalledTimes(1)
  })

  it('surfaces store errors when draft creation fails', async () => {
    const wrapper = mount(TicketDraftCard, { props: { conversationId: 'c1' } })
    const store = useTicketsStore()
    store.error = '创建工单失败'
    vi.spyOn(store, 'createDraft').mockRejectedValue(new Error('conversation_not_found'))

    await wrapper.find('[data-testid="create-draft-button"]').trigger('click')
    await settle()

    expect(wrapper.find('[data-testid="draft-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('创建工单失败')
  })
})
