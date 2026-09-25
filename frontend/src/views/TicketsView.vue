<!-- frontend/src/views/TicketsView.vue -->
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTicketsStore } from '@/stores/tickets'
import { Loader2 } from 'lucide-vue-next'

const store = useTicketsStore()
const router = useRouter()

const statusLabels: Record<string, string> = {
  draft: '草稿',
  submitted: '已提交',
  assigned: '已接单',
  in_progress: '处理中',
  waiting_user: '待补充',
  resolved_pending_confirm: '待确认',
  closed: '已解决',
  reopened: '已重开',
  cancelled: '已取消',
}

const priorityLabels: Record<string, string> = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
}

onMounted(() => {
  store.loadTickets()
})

function openTicket(id: string): void {
  router.push({ name: 'ticket-detail', params: { id } })
}

function formatTime(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="mx-auto w-full max-w-3xl px-4 py-6" data-testid="tickets-view">
    <div class="mb-4 flex items-center justify-between">
      <h2 class="text-base font-semibold text-stone-800">我的工单</h2>
      <button
        class="text-xs text-gray-500 transition-colors hover:text-stone-800"
        :disabled="store.loading"
        @click="store.loadTickets()"
      >
        刷新
      </button>
    </div>

    <div v-if="store.error" class="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
      {{ store.error }}
    </div>

    <div v-if="store.loading && store.tickets.length === 0" class="flex items-center gap-2 py-10 text-sm text-gray-400">
      <Loader2 class="h-4 w-4 animate-spin" /> 正在加载…
    </div>

    <div v-else-if="store.tickets.length === 0" class="rounded-xl border border-dashed border-gray-200 py-12 text-center text-sm text-gray-400">
      还没有工单。在聊天中遇到未解决的问题时，可以生成售后工单由客服跟进。
    </div>

    <ul v-else class="space-y-2">
      <li v-for="ticket in store.tickets" :key="ticket.id">
        <button
          class="w-full rounded-xl border border-gray-200 bg-white px-4 py-3 text-left transition-colors hover:border-stone-300 hover:bg-stone-50"
          :data-testid="`ticket-item-${ticket.ticket_number}`"
          @click="openTicket(ticket.id)"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-mono text-xs text-gray-400">{{ ticket.ticket_number }}</span>
            <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] text-stone-600">
              {{ statusLabels[ticket.status] || ticket.status }}
            </span>
            <span
              v-if="ticket.priority !== 'normal'"
              class="rounded-full border px-2 py-0.5 text-[11px]"
              :class="ticket.priority === 'urgent' || ticket.priority === 'high'
                ? 'border-red-200 bg-red-50 text-red-700'
                : 'border-gray-200 bg-gray-50 text-gray-500'"
            >
              优先级：{{ priorityLabels[ticket.priority] || ticket.priority }}
            </span>
          </div>
          <div class="mt-1 truncate text-sm font-medium text-stone-800">{{ ticket.title }}</div>
          <div class="mt-0.5 flex items-center justify-between text-xs text-gray-400">
            <span class="truncate">{{ ticket.device_model || '未识别机型' }}</span>
            <span>{{ formatTime(ticket.updated_at) }}</span>
          </div>
        </button>
      </li>
    </ul>
  </div>
</template>
