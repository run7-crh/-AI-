import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../auth'
import * as authApi from '@/api/auth'

vi.mock('@/api/auth')

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loads the current user only once', async () => {
    vi.mocked(authApi.me).mockResolvedValue({ id: '1', username: 'alice', role: 'user', is_active: true, created_at: '' })
    const store = useAuthStore()
    await Promise.all([store.ensureLoaded(), store.ensureLoaded()])
    await store.ensureLoaded()
    expect(authApi.me).toHaveBeenCalledTimes(1)
    expect(store.user?.username).toBe('alice')
    expect(store.loaded).toBe(true)
  })

  it('keeps only user, loaded, and loading state', () => {
    const store = useAuthStore()
    expect(Object.keys(store.$state).sort()).toEqual(['loaded', 'loading', 'user'])
    expect('token' in store).toBe(false)
  })
})
