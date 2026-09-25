<!-- frontend/src/components/ConversationTicketPanel.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { Ticket } from 'lucide-vue-next'
import TicketDraftModal from './TicketDraftModal.vue'

const props = defineProps<{ conversationId: string | null }>()

const open = ref(false)

function openModal(): void {
  if (props.conversationId) open.value = true
}
</script>

<template>
  <div v-if="conversationId" class="px-4 pt-2" data-testid="conversation-ticket-panel">
    <div class="flex justify-end">
      <button
        class="flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-500 transition-colors hover:border-stone-300 hover:text-stone-700"
        data-testid="toggle-ticket-panel"
        @click="openModal"
      >
        <Ticket class="h-3.5 w-3.5" />
        就此会话生成售后工单
      </button>
    </div>
    <TicketDraftModal :open="open" :conversation-id="conversationId" @close="open = false" />
  </div>
</template>
