<!-- frontend/src/views/ChatView.vue -->
<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { consumeAskQuery } from '@/utils/askQuery'
import ConversationSidebar from '@/components/ConversationSidebar.vue'
import ChatPanel from '@/components/ChatPanel.vue'

const route = useRoute()
const router = useRouter()
const store = useChatStore()

onMounted(async () => {
  await store.loadConversations()
  // 如果 URL 带 id，选中对应会话
  const id = route.params.id as string | undefined
  if (id && store.conversations.some((c) => c.id === id)) {
    await store.selectConversation(id)
  }
  // 知识图谱"一键提问"：检测 ?ask= 自动填入并发送（发送后清除参数防刷新重发）
  await consumeAskQuery(route, router, store)
})

// 监听 currentConversationId 变化，同步到 URL（可选，便于分享）
watch(
  () => store.currentConversationId,
  (newId) => {
    if (newId && route.params.id !== newId) {
      router.replace({ name: 'chat-with-id', params: { id: newId } }).catch(() => {})
    }
  }
)
</script>

<template>
  <div class="flex h-full w-full overflow-hidden bg-white">
    <ConversationSidebar />
    <ChatPanel />
  </div>
</template>
