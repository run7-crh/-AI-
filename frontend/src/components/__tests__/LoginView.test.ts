import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import LoginView from '@/views/LoginView.vue'
import { useAuthStore } from '@/stores/auth'
import * as authApi from '@/api/auth'

vi.mock('@/api/auth')

describe('LoginView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(authApi.me).mockRejectedValue(new Error('未登录'))
  })

  it('submits registration credentials and stores the authenticated user', async () => {
    vi.mocked(authApi.register).mockResolvedValue({ id: '1', username: 'alice', role: 'user', is_active: true, created_at: '' })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', component: LoginView }, { path: '/chat', component: { template: '<div />' } }] })
    await router.push('/login')
    await router.isReady()
    const wrapper = mount(LoginView, { global: { plugins: [router] } })
    await wrapper.get('button[type="button"]').trigger('click')
    await wrapper.get('[name="username"]').setValue('alice')
    await wrapper.get('[name="password"]').setValue('User-pass-1')
    await wrapper.get('form').trigger('submit')
    expect(authApi.register).toHaveBeenCalledWith({ username: 'alice', password: 'User-pass-1' })
    expect(useAuthStore().user?.username).toBe('alice')
  })
})
