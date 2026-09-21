<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const isRegister = ref(false)
const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

function boundedError(cause: unknown): string {
  const text = cause instanceof Error ? cause.message : '请求失败，请稍后重试'
  return text.slice(0, 240)
}

function safeRedirect(): string {
  const target = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  return target.startsWith('/') && !target.startsWith('//') ? target : '/chat'
}

async function submit(): Promise<void> {
  error.value = ''
  if (!username.value.trim() || password.value.length < 8) {
    error.value = '请输入用户名和至少 8 位密码'
    return
  }
  submitting.value = true
  try {
    const credentials = { username: username.value.trim(), password: password.value }
    if (isRegister.value) await auth.register(credentials)
    else await auth.login(credentials)
    await router.replace(safeRedirect())
  } catch (cause) {
    error.value = boundedError(cause)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="min-h-full flex items-center justify-center bg-stone-50 px-4">
    <form @submit.prevent="submit" class="w-full max-w-sm rounded-2xl border border-stone-200 bg-white p-6 shadow-sm space-y-4">
      <div>
        <h1 class="text-lg font-semibold text-stone-800">无人机智能售后</h1>
        <p class="mt-1 text-xs text-stone-500">{{ isRegister ? '创建账号' : '登录继续使用' }}</p>
      </div>
      <label class="block text-sm text-stone-700">用户名
        <input name="username" v-model="username" autocomplete="username" maxlength="100" class="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2" />
      </label>
      <label class="block text-sm text-stone-700">密码
        <input name="password" type="password" v-model="password" autocomplete="current-password" maxlength="128" class="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2" />
      </label>
      <p v-if="error" role="alert" class="text-sm text-red-600 break-words">{{ error }}</p>
      <button type="submit" :disabled="submitting" class="w-full rounded-lg bg-stone-800 py-2 text-sm text-white disabled:opacity-50">
        {{ submitting ? '提交中...' : (isRegister ? '注册' : '登录') }}
      </button>
      <button type="button" class="w-full text-xs text-stone-500 hover:text-stone-800" @click="isRegister = !isRegister; error = ''">
        {{ isRegister ? '已有账号？登录' : '没有账号？注册' }}
      </button>
    </form>
  </main>
</template>
