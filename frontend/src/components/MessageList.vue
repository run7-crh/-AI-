<!-- frontend/src/components/MessageList.vue -->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import UserMessage from './UserMessage.vue'
import AssistantMessage from './AssistantMessage.vue'
import EmptyState from './EmptyState.vue'

const store = useChatStore()
const listRef = ref<HTMLElement>()

async function scrollToBottom() {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
}

// 消息数量变化时滚动
watch(() => store.messages.length, scrollToBottom)
// 流式 token 到达时滚动
watch(() => store.messages.at(-1)?.content, scrollToBottom)
// 阶段变化时滚动
watch(() => store.messages.at(-1)?.currentStage, scrollToBottom)
</script>

<template>
  <div ref="listRef" class="flex-1 overflow-y-auto">
    <!-- 加载骨架屏：切换会话时展示，避免空状态闪烁 -->
    <div v-if="store.isLoadingMessages" class="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div class="flex gap-3">
        <div class="w-7 h-7 rounded-full bg-gray-200 animate-pulse shrink-0"></div>
        <div class="flex-1 space-y-2">
          <div class="h-3 w-1/3 bg-gray-200 rounded animate-pulse"></div>
          <div class="h-20 bg-gray-200 rounded-xl animate-pulse"></div>
        </div>
      </div>
      <div class="flex gap-3 justify-end">
        <div class="flex-1 space-y-2 max-w-[80%]">
          <div class="h-12 bg-gray-200 rounded-xl animate-pulse"></div>
        </div>
        <div class="w-7 h-7 rounded-full bg-gray-200 animate-pulse shrink-0"></div>
      </div>
      <div class="flex gap-3">
        <div class="w-7 h-7 rounded-full bg-gray-200 animate-pulse shrink-0"></div>
        <div class="flex-1 space-y-2">
          <div class="h-3 w-1/4 bg-gray-200 rounded animate-pulse"></div>
          <div class="h-16 bg-gray-200 rounded-xl animate-pulse"></div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <EmptyState v-else-if="store.messages.length === 0" />

    <!-- 消息列表 -->
    <div v-else class="max-w-3xl mx-auto px-4 py-6 space-y-1">
      <template v-for="m in store.messages" :key="m.id">
        <UserMessage v-if="m.role === 'user'" :message="m" />
        <AssistantMessage v-else :message="m" />
      </template>
    </div>
  </div>
</template>
