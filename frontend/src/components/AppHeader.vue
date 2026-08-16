<!-- frontend/src/components/AppHeader.vue -->
<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import { Pencil, Network } from 'lucide-vue-next'
import { ref } from 'vue'

const store = useChatStore()
const editing = ref(false)
const draftTitle = ref('')
const inputRef = ref<HTMLInputElement>()

function startEdit() {
  if (!store.currentConversation) return
  draftTitle.value = store.currentConversation.title
  editing.value = true
  setTimeout(() => inputRef.value?.focus(), 0)
}

async function commitEdit() {
  editing.value = false
  const t = draftTitle.value.trim()
  if (!t || !store.currentConversationId) return
  if (t === store.currentConversation?.title) return
  await store.updateTitle(store.currentConversationId, t)
}

function cancelEdit() {
  editing.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') commitEdit()
  else if (e.key === 'Escape') cancelEdit()
}
</script>

<template>
  <header
    class="h-14 border-b border-gray-200/80 bg-white/90 backdrop-blur flex items-center justify-between px-4 shrink-0"
  >
    <div class="flex items-center gap-3 min-w-0 flex-1">
      <!-- 抽象几何 Logo：双圆交叠，象征知识连接 -->
      <div class="shrink-0 flex items-center justify-center">
        <svg width="28" height="28" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="12" cy="16" r="8" class="fill-stone-800/90" />
          <circle cx="20" cy="16" r="8" class="fill-amber-600/85 mix-blend-multiply" />
          <circle cx="16" cy="22" r="6" class="fill-stone-500/60 mix-blend-multiply" />
        </svg>
      </div>

      <div v-if="!editing" class="flex items-center gap-1.5 min-w-0">
        <h1 class="text-sm font-semibold text-stone-800 truncate tracking-tight">
          {{ store.currentConversation?.title || '智识助手' }}
        </h1>
        <button
          v-if="store.currentConversation"
          @click="startEdit"
          class="text-gray-400 hover:text-stone-700 transition-colors p-0.5 opacity-0 hover:opacity-100 focus:opacity-100"
          title="重命名"
        >
          <Pencil class="w-3.5 h-3.5" />
        </button>
      </div>
      <input
        v-else
        ref="inputRef"
        v-model="draftTitle"
        @keydown="onKeydown"
        @blur="commitEdit"
        maxlength="100"
        class="text-sm font-semibold text-stone-800 border border-stone-300 rounded-lg px-2 py-0.5 focus:outline-none focus:ring-2 focus:ring-stone-400/50 max-w-xs bg-transparent"
      />
    </div>

    <!-- 知识图谱入口 -->
    <nav class="flex items-center gap-2 shrink-0">
      <RouterLink
        to="/graph"
        class="flex items-center gap-1.5 text-xs text-gray-500 hover:text-stone-800 border border-gray-200 hover:border-stone-300 rounded-lg px-2.5 py-1.5 transition-colors"
        title="概念知识图谱"
      >
        <Network class="w-3.5 h-3.5" /> 知识图谱
      </RouterLink>
    </nav>
  </header>
</template>
