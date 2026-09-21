import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Credentials, User } from '@/types'
import * as authApi from '@/api/auth'
import { useChatStore } from './chat'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loaded = ref(false)
  const loading = ref(false)
  const isAdmin = computed(() => user.value?.role === 'admin')
  let loadPromise: Promise<void> | null = null

  async function ensureLoaded(): Promise<void> {
    if (loaded.value) return
    if (loadPromise) return loadPromise
    loading.value = true
    loadPromise = authApi.me()
      .then((currentUser) => { user.value = currentUser })
      .catch(() => { user.value = null })
      .finally(() => {
        loaded.value = true
        loading.value = false
        loadPromise = null
      })
    return loadPromise
  }

  async function login(credentials: Credentials): Promise<User> {
    const currentUser = await authApi.login(credentials)
    useChatStore().resetSession()
    user.value = currentUser
    loaded.value = true
    return currentUser
  }

  async function register(credentials: Credentials): Promise<User> {
    const currentUser = await authApi.register(credentials)
    useChatStore().resetSession()
    user.value = currentUser
    loaded.value = true
    return currentUser
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } finally {
      useChatStore().resetSession()
      user.value = null
      loaded.value = true
    }
  }

  function clear(): void {
    useChatStore().resetSession()
    user.value = null
    loaded.value = true
  }

  if (typeof window !== 'undefined') window.addEventListener('auth-expired', clear)

  return { user, isAdmin, loaded, loading, ensureLoaded, login, register, logout, clear }
})
