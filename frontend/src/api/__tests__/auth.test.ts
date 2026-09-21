import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiFetch } from '../http'
import { login, logout, me, register } from '../auth'

describe('authenticated HTTP transport', () => {
  beforeEach(async () => {
    vi.restoreAllMocks()
    vi.stubGlobal('fetch', vi.fn())
    vi.mocked(fetch).mockResolvedValue(new Response('{}', { status: 200 }))
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ id: '1', username: 'alice' }), { status: 200 }))
    await login({ username: 'alice', password: 'pass' })
    vi.mocked(fetch).mockClear()
  })

  it('sends credentials and exposes a structured 401 error', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ detail: '未登录' }), { status: 401 }))
    const expired = vi.fn()
    window.addEventListener('auth-expired', expired)
    await expect(apiFetch('/api/conversations')).rejects.toMatchObject({ status: 401, detail: '未登录' })
    expect(fetch).toHaveBeenCalledWith('/api/conversations', expect.objectContaining({ credentials: 'include' }))
    expect(expired).toHaveBeenCalledTimes(1)
    window.removeEventListener('auth-expired', expired)
  })

  it('dispatches auth-expired only once for repeated 401 responses', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('', { status: 401 }))
    const expired = vi.fn()
    window.addEventListener('auth-expired', expired)
    await expect(apiFetch('/a')).rejects.toBeInstanceOf(ApiError)
    await expect(apiFetch('/b')).rejects.toBeInstanceOf(ApiError)
    expect(expired).toHaveBeenCalledTimes(1)
    window.removeEventListener('auth-expired', expired)
  })

  it('exposes cookie-auth endpoints', async () => {
    vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({ id: '1', username: 'alice' }), { status: 200 }))
    await register({ username: 'alice', password: 'pass' })
    await login({ username: 'alice', password: 'pass' })
    await me()
    await logout()
    expect(fetch).toHaveBeenNthCalledWith(1, '/api/auth/register', expect.objectContaining({ method: 'POST', credentials: 'include' }))
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/auth/login', expect.objectContaining({ method: 'POST', credentials: 'include' }))
    expect(fetch).toHaveBeenNthCalledWith(3, '/api/auth/me', expect.objectContaining({ credentials: 'include' }))
    expect(fetch).toHaveBeenNthCalledWith(4, '/api/auth/logout', expect.objectContaining({ method: 'POST', credentials: 'include' }))
  })

  it('does not rearm expiry notifications for unrelated successful requests', async () => {
    const expired = vi.fn()
    window.addEventListener('auth-expired', expired)
    vi.mocked(fetch).mockResolvedValueOnce(new Response('', { status: 401 }))
    await expect(apiFetch('/private')).rejects.toBeInstanceOf(ApiError)
    await apiFetch('/public')
    vi.mocked(fetch).mockResolvedValueOnce(new Response('', { status: 401 }))
    await expect(apiFetch('/private')).rejects.toBeInstanceOf(ApiError)
    expect(expired).toHaveBeenCalledTimes(1)
    await login({ username: 'alice', password: 'pass' })
    vi.mocked(fetch).mockResolvedValueOnce(new Response('', { status: 401 }))
    await expect(apiFetch('/private')).rejects.toBeInstanceOf(ApiError)
    expect(expired).toHaveBeenCalledTimes(2)
    window.removeEventListener('auth-expired', expired)
  })
})
