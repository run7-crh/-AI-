<!-- frontend/src/components/UserMessage.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import type { Message } from '@/types'
import { useChatStore } from '@/stores/chat'
import { User, Copy, Check, Pencil } from 'lucide-vue-next'

const props = defineProps<{ message: Message }>()
const store = useChatStore()
const copied = ref(false)

async function copyContent(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    // 安全上下文不可用则静默失败
  }
}

function editMessage() {
  store.editUserMessage(props.message.id)
}
</script>

<template>
  <div class="group flex justify-end gap-3 py-3">
    <div class="flex flex-col items-end gap-1 max-w-[80%]">
      <div class="bg-stone-800 text-white rounded-2xl rounded-br-sm px-4 py-2.5 shadow-sm">
        <p class="whitespace-pre-wrap break-words text-sm leading-relaxed">
          {{ message.content }}
        </p>
      </div>

      <!-- 操作菜单 -->
      <div
        class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity px-1"
      >
        <button
          @click="copyContent(message.content)"
          class="flex items-center gap-1 text-[11px] text-gray-500 hover:text-stone-700 px-1.5 py-0.5 rounded hover:bg-gray-100 transition-colors"
          title="复制"
        >
          <Check v-if="copied" class="w-3 h-3" />
          <Copy v-else class="w-3 h-3" />
          {{ copied ? '已复制' : '复制' }}
        </button>
        <button
          @click="editMessage"
          class="flex items-center gap-1 text-[11px] text-gray-500 hover:text-stone-700 px-1.5 py-0.5 rounded hover:bg-gray-100 transition-colors"
          title="编辑"
        >
          <Pencil class="w-3 h-3" />
          编辑
        </button>
      </div>
    </div>

    <!-- 用户头像 -->
    <div
      class="shrink-0 w-7 h-7 rounded-full bg-stone-200 flex items-center justify-center text-stone-600"
    >
      <User class="w-4 h-4" />
    </div>
  </div>
</template>
