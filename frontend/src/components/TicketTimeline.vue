<!-- frontend/src/components/TicketTimeline.vue -->
<script setup lang="ts">
import type { TicketEvent } from '@/types'

const props = defineProps<{ events: TicketEvent[] }>()

// internal_note is admin-only context; the backend already filters it from
// user responses.  The defensive skip here keeps the component safe if it is
// ever reused with unfiltered data.
const INTERNAL_EVENT_TYPES = new Set(['internal_note'])

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
}

const actorLabels: Record<string, string> = {
  user: '用户',
  admin: '客服',
  agent: 'Agent',
  system: '系统',
}

const visibleEvents = props.events.filter((event) => !INTERNAL_EVENT_TYPES.has(event.event_type))

function eventLabel(event: TicketEvent): string {
  return eventLabels[event.event_type] || event.event_type
}

function formatTime(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <ol class="space-y-3" data-testid="ticket-timeline">
    <li v-for="event in visibleEvents" :key="event.id" class="flex items-start gap-3">
      <span
        class="mt-1 h-2 w-2 shrink-0 rounded-full"
        :class="event.actor_type === 'admin' ? 'bg-stone-700' : 'bg-amber-500'"
      ></span>
      <div class="min-w-0 flex-1 text-xs">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-semibold text-stone-800">{{ eventLabel(event) }}</span>
          <span class="text-gray-400">{{ actorLabels[event.actor_type] || event.actor_type }}</span>
          <span class="text-gray-300">{{ formatTime(event.created_at) }}</span>
        </div>
        <p v-if="event.body" class="mt-1 whitespace-pre-wrap break-words text-gray-600">{{ event.body }}</p>
      </div>
    </li>
    <li v-if="visibleEvents.length === 0" class="text-xs text-gray-400">暂无处理记录</li>
  </ol>
</template>
