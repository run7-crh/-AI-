<script setup lang="ts">
import { onMounted, ref } from 'vue'
import * as adminApi from '@/api/admin'
import { rebuildIndex } from '@/api/graph'
import type { FeedbackStats, User } from '@/types'

const users = ref<User[]>([])
const stats = ref<FeedbackStats | null>(null)
const logs = ref<string[]>([])
const error = ref('')
const busy = ref(false)
const newUsername = ref('')
const newPassword = ref('')
const resetPasswords = ref<Record<string, string>>({})
const importInput = ref<HTMLInputElement>()

function showError(cause: unknown): void { error.value = (cause instanceof Error ? cause.message : '操作失败').slice(0, 240) }
async function refresh(): Promise<void> {
  try { [users.value, stats.value, logs.value] = await Promise.all([adminApi.listUsers(), adminApi.feedbackStats().catch(() => null), adminApi.readLogs().then((x) => x.lines).catch(() => [])]) } catch (cause) { showError(cause) }
}
async function createUser(): Promise<void> {
  busy.value = true; try { await adminApi.createUser({ username: newUsername.value.trim(), password: newPassword.value }); newUsername.value = ''; newPassword.value = ''; await refresh() } catch (cause) { showError(cause) } finally { busy.value = false }
}
async function toggle(user: User): Promise<void> { try { await adminApi.setUserActive(user.id, !user.is_active); await refresh() } catch (cause) { showError(cause) } }
async function reset(user: User): Promise<void> { const password = resetPasswords.value[user.id] || ''; try { await adminApi.resetUserPassword(user.id, password); resetPasswords.value[user.id] = '' } catch (cause) { showError(cause) } }
async function remove(user: User): Promise<void> { if (!window.confirm(`删除用户 ${user.username}？`)) return; try { await adminApi.deleteUser(user.id); await refresh() } catch (cause) { showError(cause) } }
async function importFiles(): Promise<void> { const files = Array.from(importInput.value?.files || []); if (!files.length) return; try { await adminApi.importKnowledgeBase(files); if (importInput.value) importInput.value.value = ''; } catch (cause) { showError(cause) } }
async function rebuild(): Promise<void> { try { await rebuildIndex() } catch (cause) { showError(cause) } }
onMounted(refresh)
</script>

<template>
  <main class="h-full overflow-y-auto bg-stone-50 p-6 space-y-5">
    <div class="flex items-center justify-between"><h1 class="text-lg font-semibold text-stone-800">管理员控制台</h1><button @click="refresh" class="text-xs text-stone-500">刷新</button></div>
    <p v-if="error" role="alert" class="rounded-lg bg-red-50 p-3 text-sm text-red-700 break-words">{{ error }}</p>
    <section class="rounded-xl border bg-white p-4 space-y-3"><h2 class="font-medium">用户管理</h2><div class="flex gap-2"><input v-model="newUsername" placeholder="用户名" class="rounded border px-2 py-1 text-sm" /><input v-model="newPassword" type="password" placeholder="初始密码" class="rounded border px-2 py-1 text-sm" /><button :disabled="busy" @click="createUser" class="rounded bg-stone-800 px-3 py-1 text-xs text-white">创建</button></div><div v-for="user in users" :key="user.id" class="flex flex-wrap items-center gap-2 border-t pt-2 text-sm"><span class="w-28">{{ user.username }}</span><span class="text-xs text-stone-500">{{ user.role }} · {{ user.is_active ? '启用' : '停用' }}</span><button @click="toggle(user)" class="text-xs text-stone-600">{{ user.is_active ? '停用' : '启用' }}</button><input v-model="resetPasswords[user.id]" type="password" placeholder="新密码" class="rounded border px-2 py-1 text-xs" /><button @click="reset(user)" class="text-xs text-stone-600">重置密码</button><button @click="remove(user)" class="text-xs text-red-600">删除</button></div></section>
    <section class="grid gap-4 md:grid-cols-2"><div class="rounded-xl border bg-white p-4"><h2 class="font-medium">反馈统计</h2><pre class="mt-2 text-xs text-stone-600">{{ stats ? JSON.stringify(stats, null, 2) : '暂无数据' }}</pre></div><div class="rounded-xl border bg-white p-4"><h2 class="font-medium">最近日志</h2><pre class="mt-2 max-h-48 overflow-auto whitespace-pre-wrap text-xs text-stone-600">{{ logs.join('\n') || '暂无日志' }}</pre></div></section>
    <section class="rounded-xl border bg-white p-4 space-y-3"><h2 class="font-medium">知识库</h2><input ref="importInput" type="file" multiple accept=".md,.markdown,text/markdown" /><div class="flex gap-2"><button @click="importFiles" class="rounded bg-stone-800 px-3 py-1 text-xs text-white">导入 Markdown</button><button @click="rebuild" class="rounded border px-3 py-1 text-xs">单独重建索引</button></div></section>
  </main>
</template>
