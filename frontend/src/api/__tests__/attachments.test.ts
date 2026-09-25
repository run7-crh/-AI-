import { describe, expect, it, vi, beforeEach } from 'vitest'
import { uploadAttachments, deleteAttachment, listAttachments } from '../attachments'
import { ApiError } from '../http'
import { login } from '../auth'

class FakeXHR {
  static instances: FakeXHR[] = []
  method = ''
  url = ''
  requestBody: FormData | null = null
  status = 201
  withCredentials = false
  response = JSON.stringify({ attachments: [{ id: 'att_1', original_name: 'a.txt' }] })
  readyState = 0
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  upload = { onprogress: null as ((event: ProgressEvent) => void) | null }

  constructor() { FakeXHR.instances.push(this) }
  open(method: string, url: string) { this.method = method; this.url = url }
  setRequestHeader() {}
  send(body: FormData) {
    this.requestBody = body
    this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 } as ProgressEvent)
    this.readyState = 4
    this.onload?.()
  }
}

describe('attachment API', () => {
  beforeEach(() => {
    FakeXHR.instances = []
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    vi.stubGlobal('fetch', vi.fn())
  })

  it('uploads supported files as multipart and reports progress', async () => {
    const progress: number[] = []
    const file = new File(['hello'], 'notes.txt', { type: 'text/plain' })
    const result = await uploadAttachments('conv-1', [file], (value) => progress.push(value))

    const xhr = FakeXHR.instances[0]
    expect(xhr.method).toBe('POST')
    expect(xhr.withCredentials).toBe(true)
    expect(xhr.url).toBe('/api/conversations/conv-1/attachments')
    expect(xhr.requestBody?.getAll('files')).toHaveLength(1)
    expect(progress).toEqual([50, 100])
    expect(result.attachments[0].id).toBe('att_1')
  })

  it('uses the conversation scoped endpoints for listing and deleting', async () => {
    ;(fetch as any).mockResolvedValue({
      ok: true,
      json: async () => [],
    })
    await listAttachments('conv-1')
    expect(fetch).toHaveBeenCalledWith('/api/conversations/conv-1/attachments', { credentials: 'include' })

    ;(fetch as any).mockResolvedValue({ ok: true, json: async () => ({ success: true }) })
    await deleteAttachment('conv-1', 'att_1')
    expect(fetch).toHaveBeenCalledWith('/api/conversations/conv-1/attachments/att_1', { method: 'DELETE', credentials: 'include' })
  })

  it('uses structured errors and one expiry event for repeated failed uploads', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('{}'))
    await login({ username: 'alice', password: 'pass' })
    const expired = vi.fn()
    window.addEventListener('auth-expired', expired)
    const send = vi.spyOn(FakeXHR.prototype, 'send').mockImplementation(function (this: FakeXHR) {
      this.status = 401
      this.response = JSON.stringify({ detail: '登录失效' })
      this.onload?.()
    })
    await expect(uploadAttachments('conv-1', [])).rejects.toMatchObject({ status: 401, detail: '登录失效' })
    await expect(uploadAttachments('conv-1', [])).rejects.toBeInstanceOf(ApiError)
    expect(expired).toHaveBeenCalledTimes(1)
    send.mockRestore()
    window.removeEventListener('auth-expired', expired)
  })
})
