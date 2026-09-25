<!-- frontend/src/components/ChatPanel.vue -->
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import AppHeader from './AppHeader.vue'
import MessageList from './MessageList.vue'
import InputBox from './InputBox.vue'
import ConversationTicketPanel from './ConversationTicketPanel.vue'
import { AlertCircle, X, RotateCcw } from 'lucide-vue-next'

const store = useChatStore()
const inputBoxRef = ref<InstanceType<typeof InputBox>>()

async function onRetry() {
  await store.retryLastMessage()
}

function copyLastAssistant() {
  const last = store.lastAssistantMessage
  if (last?.content) {
    navigator.clipboard.writeText(last.content).catch(() => {})
  }
}

function onKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement
  const isInput =
    target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable

  // Esc：停止生成
  if (e.key === 'Escape') {
    if (store.isStreaming) {
      e.preventDefault()
      store.stopStreaming()
    }
    return
  }

  // 以下快捷键在输入框内不触发（避免与输入冲突）
  if (isInput) return

  // /：聚焦输入框
  if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault()
    inputBoxRef.value?.focus()
    return
  }

  // Ctrl/Cmd + Shift + C：复制最后一条 AI 回复
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'c') {
    e.preventDefault()
    copyLastAssistant()
    return
  }

  // Ctrl/Cmd + N：新建会话
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
    e.preventDefault()
    store.createNewConversation()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="flex-1 flex flex-col h-full min-w-0">
    <AppHeader />

    <!-- 错误提示条 -->
    <div
      v-if="store.error"
      class="flex items-center gap-3 px-4 py-2.5 bg-amber-50/80 border-b border-amber-100 text-sm text-amber-900"
    >
      <AlertCircle class="w-4 h-4 shrink-0 text-amber-600" />
      <span class="flex-1">{{ store.error }}</span>
      <button
        @click="onRetry"
        class="flex items-center gap-1 px-2 py-1 rounded-md bg-white border border-amber-200 text-amber-700 hover:bg-amber-50 hover:border-amber-300 transition-colors text-xs font-medium"
      >
        <RotateCcw class="w-3 h-3" />
        重试
      </button>
      <button
        @click="store.clearError()"
        class="text-amber-600 hover:text-amber-800 p-0.5 rounded hover:bg-amber-100/50 transition-colors"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <MessageList />
    <!-- 常驻建单入口：任何会话都可主动生成售后工单（服务端幂等，已有工单会原样返回） -->
    <ConversationTicketPanel :conversation-id="store.currentConversationId" />
    <InputBox ref="inputBoxRef" />
  </div>
</template>
