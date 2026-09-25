<!-- frontend/src/views/TicketDetailView.vue -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useTicketsStore } from '@/stores/tickets'
import TicketTimeline from '@/components/TicketTimeline.vue'
import { Loader2, ArrowLeft } from 'lucide-vue-next'

const route = useRoute()
const store = useTicketsStore()
const messageDraft = ref('')

const statusLabels: Record<string, string> = {
  draft: '草稿',
  submitted: '已提交',
  assigned: '已接单',
  in_progress: '处理中',
  waiting_user: '待补充',
  resolved_pending_confirm: '待确认解决',
  closed: '已解决',
  reopened: '已重开',
  cancelled: '已取消',
}

const ticket = computed(() => store.currentTicket)
const canSubmit = computed(() => ticket.value?.status === 'draft')
const canConfirm = computed(() => ticket.value?.status === 'resolved_pending_confirm')
const evidenceAttachments = computed(() =>
  (store.current?.evidence ?? []).filter((item) => item.evidence_type === 'attachment'),
)

onMounted(() => {
  const id = route.params.id
  if (typeof id === 'string') store.openDetail(id)
})

async function submitTicket(): Promise<void> {
  if (!ticket.value) return
  try {
    await store.submit(ticket.value.id)
  } catch {
    // store.error already carries the message for display
  }
}

async function confirmResolution(): Promise<void> {
  if (!ticket.value) return
  try {
    await store.confirmResolution(ticket.value.id)
  } catch {
    // handled via store.error
  }
}

async function reopenTicket(): Promise<void> {
  if (!ticket.value) return
  try {
    await store.reopen(ticket.value.id)
  } catch {
    // handled via store.error
  }
}

async function sendMessage(): Promise<void> {
  const body = messageDraft.value.trim()
  if (!body || !ticket.value) return
  try {
    await store.addMessage(ticket.value.id, body)
    messageDraft.value = ''
  } catch {
    // handled via store.error
  }
}
</script>

<template>
  <div class="mx-auto w-full max-w-3xl px-4 py-6" data-testid="ticket-detail-view">
    <button
      class="mb-3 flex items-center gap-1 text-xs text-gray-500 transition-colors hover:text-stone-800"
      @click="store.closeDetail(); $router.back()"
    >
      <ArrowLeft class="h-3.5 w-3.5" /> 返回列表
    </button>

    <div v-if="store.loading && !ticket" class="flex items-center gap-2 py-10 text-sm text-gray-400">
      <Loader2 class="h-4 w-4 animate-spin" /> 正在加载…
    </div>

    <div v-else-if="!ticket" class="rounded-xl border border-dashed border-gray-200 py-12 text-center text-sm text-gray-400">
      工单不存在或已被删除。
    </div>

    <template v-else>
      <div class="rounded-xl border border-gray-200 bg-white p-4">
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-mono text-xs text-gray-400" data-testid="detail-number">{{ ticket.ticket_number }}</span>
          <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] text-stone-600" data-testid="detail-status">
            {{ statusLabels[ticket.status] || ticket.status }}
          </span>
          <span
            v-if="ticket.safety_level === 'high'"
            class="rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-[11px] text-red-700"
          >
            高风险
          </span>
        </div>
        <h3 class="mt-1.5 text-base font-semibold text-stone-800" data-testid="detail-title">{{ ticket.title }}</h3>
        <p class="mt-1 whitespace-pre-wrap text-xs text-gray-500">{{ ticket.problem_summary }}</p>

        <dl class="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <div class="flex gap-1"><dt class="text-gray-400">机型</dt><dd class="text-stone-700">{{ ticket.device_model || '未识别' }}</dd></div>
          <div class="flex gap-1"><dt class="text-gray-400">故障分类</dt><dd class="text-stone-700">{{ ticket.fault_category || '未识别' }}</dd></div>
          <div v-if="ticket.escalation_reason" class="col-span-2 flex gap-1">
            <dt class="text-gray-400">升级原因</dt><dd class="text-red-700">{{ ticket.escalation_reason }}</dd>
          </div>
          <div v-if="ticket.resolution_summary" class="col-span-2 flex gap-1">
            <dt class="text-gray-400">处理结论</dt><dd class="text-emerald-700" data-testid="resolution-summary">{{ ticket.resolution_summary }}</dd>
          </div>
        </dl>

        <div v-if="evidenceAttachments.length" class="mt-3 text-xs text-gray-500">
          <span class="font-medium text-stone-700">案件附件证据：</span>
          {{ evidenceAttachments.length }} 个（随工单保留，到期前不会被自动清理）
        </div>

        <div class="mt-4 flex flex-wrap items-center gap-2">
          <button
            v-if="canSubmit"
            class="rounded-lg bg-stone-800 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="store.acting"
            data-testid="detail-submit"
            @click="submitTicket"
          >
            提交工单
          </button>
          <template v-if="canConfirm">
            <button
              class="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="store.acting"
              data-testid="detail-confirm"
              @click="confirmResolution"
            >
              已解决，确认关闭
            </button>
            <button
              class="rounded-lg border border-stone-300 px-3 py-1.5 text-xs font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="store.acting"
              data-testid="detail-reopen"
              @click="reopenTicket"
            >
              仍未解决，重开工单
            </button>
          </template>
        </div>
        <div v-if="store.error" class="mt-2 text-xs text-red-600" data-testid="detail-error">{{ store.error }}</div>
      </div>

      <div class="mt-4 rounded-xl border border-gray-200 bg-white p-4">
        <h4 class="mb-3 text-sm font-semibold text-stone-800">处理进度</h4>
        <TicketTimeline v-if="store.current" :events="store.current.events" />

        <div class="mt-4 border-t border-gray-100 pt-3">
          <textarea
            v-model="messageDraft"
            rows="2"
            maxlength="4000"
            placeholder="补充问题信息、排查结果或联系方式…"
            class="w-full resize-none rounded-lg border border-gray-200 px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-stone-300"
            data-testid="message-input"
          ></textarea>
          <button
            class="mt-2 rounded-lg border border-stone-300 px-3 py-1.5 text-xs font-medium text-stone-700 transition-colors hover:bg-stone-50 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="store.acting || !messageDraft.trim()"
            data-testid="send-message"
            @click="sendMessage"
          >
            发送补充信息
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
