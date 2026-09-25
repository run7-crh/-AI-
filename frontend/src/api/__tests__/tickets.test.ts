import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  addTicketMessage,
  confirmResolution,
  createDraftFromConversation,
  getTicket,
  listTickets,
  reopenTicket,
  submitTicket,
} from '../tickets'
import { ApiError } from '../http'
import { markAuthenticated } from '../http'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('ticket API', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    markAuthenticated()
  })

  it('creates a draft from a conversation with credentials and JSON body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 't1', status: 'draft' }, 201))
    vi.stubGlobal('fetch', fetchMock)

    const ticket = await createDraftFromConversation('conv-1', ['att_1'])

    expect(ticket).toMatchObject({ id: 't1', status: 'draft' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/tickets/from-conversation')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(JSON.parse(init.body)).toEqual({ conversation_id: 'conv-1', attachment_ids: ['att_1'] })
  })

  it('encodes ticket ids on list, detail and action endpoints', async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method || 'GET'
      if (url === '/api/tickets') return jsonResponse([])
      if (url === '/api/tickets/T%2F1' && method === 'GET') return jsonResponse({ ticket: { id: 'T/1' }, events: [], evidence: [] })
      return jsonResponse({ id: 'T/1', status: 'submitted' })
    })
    vi.stubGlobal('fetch', fetchMock)

    await listTickets()
    await getTicket('T/1')
    await submitTicket('T/1')
    await addTicketMessage('T/1', '补充信息')
    await confirmResolution('T/1')
    await reopenTicket('T/1')

    const urls = fetchMock.mock.calls.map((call) => String(call[0]))
    expect(urls).toEqual([
      '/api/tickets',
      '/api/tickets/T%2F1',
      '/api/tickets/T%2F1/submit',
      '/api/tickets/T%2F1/messages',
      '/api/tickets/T%2F1/confirm-resolution',
      '/api/tickets/T%2F1/reopen',
    ])
    const messageCall = fetchMock.mock.calls[3]
    expect(messageCall[1].method).toBe('POST')
    expect(JSON.parse(messageCall[1].body)).toEqual({ body: '补充信息' })
  })

  it('parses backend detail codes into ApiError and notifies auth expiry once', async () => {
    const expired = vi.fn()
    window.addEventListener('auth-expired', expired)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'conversation_not_found' }), { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: '未登录' }), { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(createDraftFromConversation('conv-x')).rejects.toMatchObject({
      status: 404,
      detail: 'conversation_not_found',
    })
    await expect(listTickets()).rejects.toBeInstanceOf(ApiError)
    expect(expired).toHaveBeenCalledTimes(1)
    window.removeEventListener('auth-expired', expired)
  })
})
