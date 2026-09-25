<!-- frontend/src/components/ConversationTicketPanel.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { Loader2, Ticket } from 'lucide-vue-next'
import { useTicketsStore } from '@/stores/tickets'
import TicketDraftCard from './TicketDraftCard.vue'

const props = defineProps<{ conversationId: string | null }>()

const store = useTicketsStore()
const open = ref(false)

function toggle(): void {
  if (!props.conversationId) return
  open.value = !open.value
}
</script>

<template>
  <div v-if="conversationId" class="px-4 pt-2" data-testid="conversation-ticket-panel">
    <TicketDraftCard v-if="open" :conversation-id="conversationId" class="mb-2" />
    <div class="flex justify-end">
      <button
        class="flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-500 transition-colors hover:border-stone-300 hover:text-stone-700 disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="store.acting"
        data-testid="toggle-ticket-panel"
        @click="toggle"
      >
        <Loader2 v-if="store.acting" class="h-3.5 w-3.5 animate-spin" />
        <Ticket v-else class="h-3.5 w-3.5" />
        {{ open ? '收起工单' : '就此会话生成售后工单' }}
      </button>
    </div>
  </div>
</template>
