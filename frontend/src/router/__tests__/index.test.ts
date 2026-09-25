import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { router } from '@/router'
import { useAuthStore } from '@/stores/auth'

describe('router authentication guards', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.loaded = true
    auth.user = { id: '1', username: 'alice', role: 'user', is_active: true, created_at: '' }
    await router.push('/login')
  })

  it('redirects a normal user away from the admin page', async () => {
    await router.push('/admin')
    expect(router.currentRoute.value.fullPath).toBe('/chat')
  })
})
