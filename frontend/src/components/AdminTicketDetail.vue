<!-- frontend/src/components/AdminTicketDetail.vue -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { TicketDetail, TicketEvent, TicketStatus, User } from '@/types'
import {
  appendTicketEvent,
  getTicketDetail,
  updateTicket,
  type AdminTicketUpdate,
} from '@/api/adminTickets'

const props = defineProps<{ ticketId: string; isAdmin?: boolean; assigneeOptions?: User[] }>()
const emit = defineEmits<{ back: [] }>()

// Frontend copy of the backend whitelist (single source of truth stays in
// ticket_service.py); used only to enable/disable buttons, never to bypass it.
const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  draft: ['submitted', 'cancelled'],
  submitted: ['assigned', 'waiting_user', 'cancelled'],
  assigned: ['in_progress', 'waiting_user', 'cancelled'],
  in_progress: ['waiting_user', 'resolved_pending_confirm', 'cancelled'],
  waiting_user: ['in_progress', 'cancelled'],
  resolved_pending_confirm: ['closed', 'reopened'],
  reopened: ['assigned', 'in_progress', 'waiting_user'],
  closed: [],
  cancelled: [],
}

const statusTargets: TicketStatus[] = [
  'submitted', 'assigned', 'in_progress', 'waiting_user',
  'resolved_pending_confirm', 'closed', 'reopened', 'cancelled',
]

const detail = ref<TicketDetail | null>(null)
const error = ref<string | null>(null)
const busy = ref(false)
const assigneeDraft = ref('')
const assigneeSelected = ref('')
const resolutionDraft = ref('')
const eventBody = ref('')
const eventType = ref<'public_reply' | 'internal_note'>('public_reply')

const ticket = computed(() => detail.value?.ticket ?? null)
const hasAssigneeOptions = computed(() => (props.assigneeOptions?.length ?? 0) > 0)

const eventLabels: Record<string, string> = {
  created: '创建工单草稿',
  submitted: '提交工单',
  assigned: '客服接单',
  started: '开始处理',
  waiting_user: '等待用户补充',
  resolved: '给出处理结论',
  user_confirmed: '用户确认解决',
  admin_closed: '客服关闭工单',
  reopened: '工单重开',
  cancelled: '工单取消',
  status_changed: '状态变更',
  public_reply: '客服回复',
  public_message: '用户补充',
  internal_note: '内部备注',
  agent_suggestion: 'AI 建议',
}

const actorLabels: Record<string, string> = {
  user: '用户',
  admin: '客服',
  agent: 'Agent',
  system: '系统',
}

function eventKind(event: TicketEvent): 'agent' | 'internal' | 'public' | 'system' {
  if (event.actor_type === 'agent') return 'agent'
  if (event.event_type === 'internal_note') return 'internal'
  return 'public'
}

function eventLabel(event: TicketEvent): string {
  return eventLabels[event.event_type] || event.event_type
}

function isTransitionAllowed(target: string): boolean {
  const current = ticket.value?.status
  if (!current) return false
  return (ALLOWED_TRANSITIONS[current] || []).includes(target)
}

async function load(): Promise<void> {
  error.value = null
  try {
    detail.value = await getTicketDetail(props.ticketId)
    assigneeDraft.value = ticket.value?.assignee_user_id || ''
    assigneeSelected.value = props.assigneeOptions?.some(
      (user) => user.id === ticket.value?.assignee_user_id,
    )
      ? (ticket.value?.assignee_user_id ?? '')
      : ''
    resolutionDraft.value = ticket.value?.resolution_summary || ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '加载工单详情失败'
  }
}

function currentAssignee(): string | undefined {
  const value = hasAssigneeOptions.value ? assigneeSelected.value : assigneeDraft.value
  return value || undefined
}

async function applyUpdate(payload: AdminTicketUpdate): Promise<void> {
  busy.value = true
  error.value = null
  try {
    await updateTicket(props.ticketId, payload)
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '更新工单失败'
  } finally {
    busy.value = false
  }
}

async function sendEvent(): Promise<void> {
  const body = eventBody.value.trim()
  if (!body) return
  busy.value = true
  error.value = null
  try {
    detail.value = await appendTicketEvent(props.ticketId, eventType.value, body)
    eventBody.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '发送事件失败'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div data-testid="admin-ticket-detail">
    <button
      class="mb-2 text-xs text-stone-500 transition-colors hover:text-stone-800"
      @click="emit('back')"
    >
      ← 返回队列
    </button>

    <div v-if="!ticket" class="py-6 text-center text-xs text-gray-400">
      {{ error || '正在加载…' }}
    </div>

    <template v-else>
      <div class="rounded-lg border border-gray-200 p-3">
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <span class="font-mono text-gray-400">{{ ticket.ticket_number }}</span>
          <span class="rounded-full border border-stone-200 bg-stone-50 px-1.5 py-0.5">{{ ticket.status }}</span>
          <span v-if="ticket.safety_level === 'high'" class="rounded-full border border-red-200 bg-red-50 px-1.5 py-0.5 text-red-700">高风险</span>
        </div>
        <div class="mt-1 text-sm font-medium text-stone-800">{{ ticket.title }}</div>
        <p class="mt-1 whitespace-pre-wrap text-xs text-gray-500">{{ ticket.problem_summary }}</p>
        <dl class="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <div class="flex gap-1"><dt class="text-gray-400">机型</dt><dd>{{ ticket.device_model || '未识别' }}</dd></div>
          <div class="flex gap-1"><dt class="text-gray-400">故障</dt><dd>{{ ticket.fault_category || '未识别' }}</dd></div>
          <div v-if="ticket.escalation_reason" class="col-span-2 flex gap-1">
            <dt class="text-gray-400">升级原因</dt><dd class="text-red-700">{{ ticket.escalation_reason }}</dd>
          </div>
        </dl>
      </div>

      <div v-if="isAdmin" class="mt-3 space-y-2 rounded-lg border border-gray-200 p-3 text-xs" data-testid="admin-actions">
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-gray-400">状态操作：</span>
          <button
            v-for="target in statusTargets"
            :key="target"
            class="rounded border px-2 py-1 transition-colors disabled:cursor-not-allowed disabled:opacity-40"
            :class="isTransitionAllowed(target)
              ? 'border-stone-300 bg-white text-stone-700 hover:bg-stone-100'
              : 'border-gray-100 bg-gray-50 text-gray-300'"
            :disabled="busy || !isTransitionAllowed(target)"
            :data-testid="`status-button-${target}`"
            @click="applyUpdate({ status: target })"
          >
            {{ target }}
          </button>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <select
            v-if="hasAssigneeOptions"
            v-model="assigneeSelected"
            class="rounded border border-gray-200 px-1.5 py-1"
            data-testid="assignee-select"
          >
            <option value="">选择负责人…</option>
            <option v-for="user in assigneeOptions" :key="user.id" :value="user.id">
              {{ user.username }}（{{ user.role }}）
            </option>
          </select>
          <input
            v-else
            v-model="assigneeDraft"
            class="w-32 rounded border border-gray-200 px-2 py-1"
            placeholder="负责人 ID"
            data-testid="assignee-input"
          />
          <button
            class="rounded border border-stone-300 px-2 py-1 disabled:opacity-40"
            :disabled="busy"
            data-testid="assign-button"
            @click="applyUpdate({ assignee_user_id: currentAssignee() })"
          >
            转派
          </button>
          <input
            v-model="resolutionDraft"
            class="min-w-48 flex-1 rounded border border-gray-200 px-2 py-1"
            placeholder="处理结论（随 resolved 状态提交）"
            data-testid="resolution-input"
          />
          <button
            class="rounded border border-stone-300 px-2 py-1 disabled:opacity-40"
            :disabled="busy || !resolutionDraft.trim()"
            data-testid="resolution-button"
            @click="applyUpdate({ resolution_summary: resolutionDraft || undefined })"
          >
            保存结论
          </button>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <select v-model="eventType" class="rounded border border-gray-200 px-1.5 py-1" data-testid="event-type">
            <option value="public_reply">公开回复</option>
            <option value="internal_note">内部备注</option>
          </select>
          <input
            v-model="eventBody"
            class="min-w-48 flex-1 rounded border border-gray-200 px-2 py-1"
            placeholder="回复或备注内容"
            data-testid="event-body"
          />
          <button
            class="rounded border border-stone-300 px-2 py-1 disabled:opacity-40"
            :disabled="busy || !eventBody.trim()"
            data-testid="send-event"
            @click="sendEvent"
          >
            发送
          </button>
        </div>
      </div>

      <div v-if="error" class="mt-2 text-xs text-red-600">{{ error }}</div>

      <ol class="mt-3 space-y-2" data-testid="admin-timeline">
        <li
          v-for="event in detail?.events || []"
          :key="event.id"
          class="rounded-lg border px-3 py-2 text-xs"
          :class="{
            'border-indigo-200 bg-indigo-50 text-indigo-900': eventKind(event) === 'agent',
            'border-amber-200 bg-amber-50 text-amber-900': eventKind(event) === 'internal',
            'border-gray-200 bg-white text-stone-700': eventKind(event) === 'public',
          }"
          :data-testid="`event-${event.event_type}`"
        >
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-semibold">{{ eventLabel(event) }}</span>
            <span class="text-gray-400">{{ actorLabels[event.actor_type] || event.actor_type }}</span>
          </div>
          <p v-if="event.body" class="mt-1 whitespace-pre-wrap break-words">{{ event.body }}</p>
        </li>
      </ol>
    </template>
  </div>
</template>
