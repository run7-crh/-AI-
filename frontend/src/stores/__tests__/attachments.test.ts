import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useChatStore } from '../chat'
import * as convApi from '@/api/conversations'
import * as chatApi from '@/api/chat'
import * as attachmentApi from '@/api/attachments'

vi.mock('@/api/conversations')
vi.mock('@/api/chat')
vi.mock('@/api/attachments')

const readyAttachment = {
  id: 'att_1', original_name: 'flight.log', extension: 'log',
  declared_mime: 'text/plain', detected_mime: 'text/plain', size_bytes: 10,
  status: 'ready' as const, extraction_status: 'ready' as const,
  expires_at: '2099-01-01T00:00:00Z',
}

describe('chat store attachment draft', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('uploads files, sends only ready attachment ids, and clears the draft after the round', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({ id: 'c1', title: '', message_count: 0, created_at: '', updated_at: '' })
    ;(attachmentApi.uploadAttachments as any).mockResolvedValue({ attachments: [readyAttachment], count: 1 })
    ;(chatApi.streamChat as any).mockImplementation(async (request: any, cb: any) => {
      expect(request.attachment_ids).toEqual(['att_1'])
      cb.onFinal?.('答案')
      cb.onDone()
    })

    const store = useChatStore()
    await store.uploadAttachments([new File(['x'], 'flight.log', { type: 'text/plain' })])
    expect(store.pendingAttachments).toHaveLength(1)
    store.inputText = ''
    await store.sendMessage()

    expect(chatApi.streamChat).toHaveBeenCalledOnce()
    expect(store.pendingAttachments).toHaveLength(0)
    expect(store.messages[0].attachments?.[0].original_name).toBe('flight.log')
  })

  it('blocks sending when an attachment is not ready, even if text is present', async () => {
    const store = useChatStore()
    store.currentConversationId = 'c1'
    store.pendingAttachments = [{ ...readyAttachment, status: 'failed' }]
    store.inputText = '请排查'
    await store.sendMessage()
    expect(chatApi.streamChat).not.toHaveBeenCalled()
    expect(store.error).toContain('附件')
  })

  it('does not reuse expired attachments for a later round', async () => {
    const store = useChatStore()
    store.currentConversationId = 'c1'
    store.pendingAttachments = [{ ...readyAttachment, status: 'expired' }]
    store.inputText = ''
    await store.sendMessage()
    expect(chatApi.streamChat).not.toHaveBeenCalled()
    expect(store.error).toContain('附件')
  })

  it('clears unsent attachments when switching conversations', async () => {
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'c2', messages: [] })
    const store = useChatStore()
    store.pendingAttachments = [readyAttachment]
    await store.selectConversation('c2')
    expect(store.pendingAttachments).toHaveLength(0)
  })

  it('keeps a failed upload visible so the user can remove it', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({ id: 'c1', title: '', message_count: 0, created_at: '', updated_at: '' })
    ;(attachmentApi.uploadAttachments as any).mockRejectedValue(new Error('attachment_upload_failed'))
    const store = useChatStore()
    await store.uploadAttachments([new File(['x'], 'flight.log', { type: 'text/plain' })])
    expect(store.pendingAttachments[0].status).toBe('failed')
    expect(store.pendingAttachments[0].extraction_error).toContain('attachment_upload_failed')
    await store.removeAttachment(store.pendingAttachments[0].id)
    expect(store.pendingAttachments).toHaveLength(0)
  })
})
