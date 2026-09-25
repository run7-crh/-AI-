<!-- frontend/src/components/UserMessage.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import type { Message } from '@/types'
import { useChatStore } from '@/stores/chat'
import { User, Copy, Check, Pencil, Paperclip } from 'lucide-vue-next'

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

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function attachmentStatus(attachment: NonNullable<Message['attachments']>[number]): string {
  if (attachment.status === 'expired' || (attachment.expires_at && new Date(attachment.expires_at).getTime() <= Date.now())) return '已过期'
  if (attachment.status === 'failed' || attachment.extraction_status === 'failed') return '处理失败'
  if (attachment.status === 'deleted') return '已删除'
  return attachment.extraction_status === 'pending' ? '解析中' : '已就绪'
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

      <div v-if="message.attachments?.length" class="flex flex-wrap justify-end gap-1.5 max-w-full" data-testid="message-attachments">
        <div
          v-for="attachment in message.attachments"
          :key="attachment.id"
          class="min-w-0 max-w-full flex items-center gap-1.5 rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1.5 text-xs text-stone-700"
        >
          <Paperclip class="w-3.5 h-3.5 shrink-0 text-stone-500" />
          <span class="min-w-0 max-w-[12rem] truncate" :title="attachment.original_name">{{ attachment.original_name }}</span>
          <span class="shrink-0 text-gray-500">{{ attachment.extension.toUpperCase() }} · {{ formatSize(attachment.size_bytes) }}</span>
          <span class="shrink-0 text-gray-500">{{ attachmentStatus(attachment) }}</span>
        </div>
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
