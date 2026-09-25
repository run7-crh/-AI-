<!-- frontend/src/components/AdminTicketQueue.vue -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { Ticket, User } from '@/types'
import { listAllTickets, type AdminTicketFilters } from '@/api/adminTickets'
import AdminTicketDetail from './AdminTicketDetail.vue'

const props = defineProps<{ users?: User[] }>()

const tickets = ref<Ticket[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const selectedId = ref<string | null>(null)
const filters = ref<AdminTicketFilters>({})

const statusOptions = ['submitted', 'assigned', 'in_progress', 'waiting_user', 'resolved_pending_confirm', 'closed', 'reopened', 'cancelled']
const priorityOptions = ['low', 'normal', 'high', 'urgent']
const safetyOptions = ['high', 'none']

const hasFilters = computed(() => Object.values(filters.value).some((value) => Boolean(value)))

async function refresh(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    tickets.value = await listAllTickets(filters.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载工单队列失败'
  } finally {
    loading.value = false
  }
}

function setFilter(key: keyof AdminTicketFilters, value: string): void {
  filters.value = { ...filters.value, [key]: value || undefined }
  refresh()
}

function clearFilters(): void {
  filters.value = {}
  refresh()
}

function openDetail(ticket: Ticket): void {
  selectedId.value = ticket.id
}

function backToQueue(): void {
  selectedId.value = null
  refresh()
}

onMounted(refresh)
</script>

<template>
  <div data-testid="admin-ticket-queue">
    <template v-if="!selectedId">
      <div class="flex flex-wrap items-center gap-2 text-xs" data-testid="admin-ticket-filters">
        <label class="flex items-center gap-1">
          状态
          <select
            class="rounded border border-gray-200 px-1.5 py-1"
            data-testid="filter-status"
            @change="setFilter('status', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">全部</option>
            <option v-for="option in statusOptions" :key="option" :value="option">{{ option }}</option>
          </select>
        </label>
        <label class="flex items-center gap-1">
          优先级
          <select
            class="rounded border border-gray-200 px-1.5 py-1"
            data-testid="filter-priority"
            @change="setFilter('priority', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">全部</option>
            <option v-for="option in priorityOptions" :key="option" :value="option">{{ option }}</option>
          </select>
        </label>
        <label class="flex items-center gap-1">
          安全等级
          <select
            class="rounded border border-gray-200 px-1.5 py-1"
            data-testid="filter-safety"
            @change="setFilter('safety_level', ($event.target as HTMLSelectElement).value)"
          >
            <option value="">全部</option>
            <option v-for="option in safetyOptions" :key="option" :value="option">{{ option }}</option>
          </select>
        </label>
        <input
          class="w-32 rounded border border-gray-200 px-1.5 py-1"
          placeholder="负责人 ID"
          data-testid="filter-assignee"
          @keydown.enter="setFilter('assignee_user_id', ($event.target as HTMLInputElement).value)"
        />
        <button v-if="hasFilters" class="text-stone-500" @click="clearFilters">清除筛选</button>
      </div>

      <div v-if="error" class="mt-2 text-xs text-red-600">{{ error }}</div>

      <ul class="mt-2 divide-y divide-gray-100">
        <li v-for="ticket in tickets" :key="ticket.id">
          <button
            class="w-full py-2 text-left transition-colors hover:bg-stone-50"
            :data-testid="`admin-ticket-row-${ticket.ticket_number}`"
            @click="openDetail(ticket)"
          >
            <div class="flex flex-wrap items-center gap-2 text-xs">
              <span class="font-mono text-gray-400">{{ ticket.ticket_number }}</span>
              <span class="rounded-full border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-stone-600">{{ ticket.status }}</span>
              <span v-if="ticket.safety_level === 'high'" class="rounded-full border border-red-200 bg-red-50 px-1.5 py-0.5 text-red-700">高风险</span>
              <span class="text-gray-400">优先级 {{ ticket.priority }}</span>
              <span class="text-gray-400">负责人 {{ ticket.assignee_user_id || '未分配' }}</span>
            </div>
            <div class="mt-0.5 truncate text-sm text-stone-800">{{ ticket.title }}</div>
          </button>
        </li>
        <li v-if="!loading && tickets.length === 0" class="py-6 text-center text-xs text-gray-400">
          队列为空
        </li>
      </ul>
    </template>

    <AdminTicketDetail
      v-else
      :ticket-id="selectedId"
      is-admin
      :assignee-options="props.users || []"
      @back="backToQueue"
    />
  </div>
</template>
