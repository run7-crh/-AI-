<!-- frontend/src/components/TicketDraftModal.vue -->
<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { X } from 'lucide-vue-next'
import TicketDraftCard from './TicketDraftCard.vue'

const props = defineProps<{ open: boolean; conversationId: string | null }>()
const emit = defineEmits<{ close: [] }>()

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && props.open) emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label="生成售后工单"
      data-testid="ticket-draft-modal"
    >
      <div
        class="absolute inset-0 bg-stone-900/40"
        data-testid="modal-backdrop"
        @click="emit('close')"
      ></div>
      <div class="relative w-full max-w-md rounded-2xl bg-white p-4 shadow-xl">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-sm font-semibold text-stone-800">生成售后工单</h3>
          <button
            class="rounded-md p-1 text-gray-400 transition-colors hover:bg-stone-100 hover:text-stone-700"
            aria-label="关闭"
            data-testid="modal-close"
            @click="emit('close')"
          >
            <X class="h-4 w-4" />
          </button>
        </div>
        <TicketDraftCard v-if="conversationId" :conversation-id="conversationId" />
        <p v-else class="text-xs text-gray-400">
          当前没有进行中的会话，先在聊天中发起对话后再创建工单。
        </p>
        <p class="mt-3 border-t border-gray-100 pt-2 text-[11px] text-gray-400">
          同一会话只对应一张工单；草稿生成后由你确认才会提交给客服。
        </p>
      </div>
    </div>
  </Teleport>
</template>
