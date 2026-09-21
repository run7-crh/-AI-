// frontend/src/api/__tests__/conversations.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listConversations, createConversation, deleteConversation, getConversation, updateConversation } from '../conversations'

globalThis.fetch = vi.fn() as unknown as typeof fetch

describe('conversations API', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('listConversations calls GET /api/conversations', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => [] })
    await listConversations()
    expect(fetch).toHaveBeenCalledWith('/api/conversations', { credentials: 'include' })
  })

  it('createConversation calls POST with body', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ({ id: '1' }) })
    await createConversation({ title: 'test' })
    expect(fetch).toHaveBeenCalledWith('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: 'test' }),
      credentials: 'include',
    })
  })

  it('createConversation defaults to empty body', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ({ id: '1' }) })
    await createConversation()
    expect(fetch).toHaveBeenCalledWith('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
      credentials: 'include',
    })
  })

  it('getConversation calls GET /api/conversations/:id', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ({ id: 'abc', messages: [] }) })
    await getConversation('abc')
    expect(fetch).toHaveBeenCalledWith('/api/conversations/abc', { credentials: 'include' })
  })

  it('deleteConversation calls DELETE', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ({ success: true }) })
    await deleteConversation('abc')
    expect(fetch).toHaveBeenCalledWith('/api/conversations/abc', { method: 'DELETE', credentials: 'include' })
  })

  it('updateConversation calls PATCH with title', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ({ id: '1', title: '新' }) })
    await updateConversation('1', '新')
    expect(fetch).toHaveBeenCalledWith('/api/conversations/1', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: '新' }),
      credentials: 'include',
    })
  })

  it('throws on non-ok response', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 404 })
    await expect(deleteConversation('x')).rejects.toThrow('HTTP 404')
  })
})
