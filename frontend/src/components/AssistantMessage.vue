<!-- frontend/src/components/AssistantMessage.vue -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { Message, FeedbackRating, UselessReason } from '@/types'
import { useChatStore } from '@/stores/chat'
import { Copy, Check, RefreshCw, ThumbsUp, ThumbsDown, Bug, ShieldAlert, Headset, Ticket } from 'lucide-vue-next'
import MarkdownRenderer from './MarkdownRenderer.vue'
import TraceTimeline from './TraceTimeline.vue'
import SourceCard from './SourceCard.vue'
import JudgeBadges from './JudgeBadges.vue'
import TicketDraftModal from './TicketDraftModal.vue'
import { putFeedback } from '@/api/feedback'

const props = defineProps<{ message: Message }>()
const store = useChatStore()
const router = useRouter()
const copied = ref(false)

// 阶段 5：Agent 已自动创建工单草稿（仅草稿，提交仍由用户确认）
const agentTicket = computed(() =>
  props.message.recommended_action === 'create_ticket' ? props.message.agent_ticket ?? null : null
)

function openAgentTicket() {
  const ticket = agentTicket.value
  if (ticket?.id) router.push(`/tickets/${ticket.id}`)
}

const intentLabels: Record<string, string> = {
  product_parameter: '产品参数',
  technical_principle: '技术原理',
  troubleshooting: '故障排查',
  sop_operation: 'SOP 操作',
  case_reference: '模拟案例参考',
  flight_safety: '飞行安全',
  compliance_regulation: '合规与法规',
  chitchat: '闲聊',
  time_sensitive: '时效性问题',
  knowledge_gap: '知识库未覆盖问题',
}

const safetySituationLabels: Record<string, string> = {
  in_flight: '飞行中',
  landed: '已降落',
  charging: '充电中',
  unknown: '状态未知',
}

const showSafetyNotice = computed(() =>
  props.message.safety_flag === true || props.message.safety_level === 'high'
)
const safetyLevelLabel = computed(() => props.message.safety_level === 'high' ? '高风险' : '需注意')
const safetySituationLabel = computed(() => {
  const situation = props.message.safety_situation
  return situation ? safetySituationLabels[situation] || situation : ''
})
const intentLabel = computed(() => {
  const intent = props.message.intent
  return intent ? intentLabels[intent] || intent : ''
})
const attachmentStatusLabel = computed(() => {
  const status = props.message.attachment_status
  if (!status) return ''
  if (status.status === 'failed') return status.message || '附件处理失败'
  if (status.phase === 'parse') return status.status === 'ready' ? '附件已解析，正在结合本轮问题' : '正在解析附件'
  if (status.phase === 'context') return '正在载入附件上下文'
  if (status.phase === 'retrieve') return '正在检索相关售后资料'
  return status.message || ''
})

// 第 2 阶段：反馈状态（已反馈时按钮置灰）
const feedbackState = ref<FeedbackRating | null>(null)
const showUselessReasons = ref(false)

// 工单入口：只在后端明确给出 escalation_required 时展示，用户点击后弹出草稿窗口。
const showTicketDraft = ref(false)
const conversationId = computed(() => store.currentConversationId || '')
const uselessReasonOptions: { value: UselessReason; label: string }[] = [
  { value: 'irrelevant', label: '答非所问' },
  { value: 'hallucination', label: '编造' },
  { value: 'verbose', label: '太啰嗦' },
  { value: 'wrong_route', label: '路由错误' },
]

// 无来源卡片时（online/multi_step_reason 路径），清理 LLM 可能残留的 [1] [2] 引用标记。
// 正则只匹配"前面是空格或行首 + [数字] + 后面是空格/中文标点/行尾"，
// 避免误伤代码块的数组索引 arr[1] 和 markdown 链接 [text](url)。
const displayContent = computed(() => {
  if (props.message.sources && props.message.sources.length) {
    return props.message.content
  }
  return props.message.content.replace(
    /(^|\s)\[\d+\](?=[\s，。；！？、）)]|$)/g,
    '$1'
  )
})

async function copyContent(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    // 安全上下文不可用则静默失败
  }
}

function regenerate() {
  store.regenerateResponse(props.message.id)
}

// 第 2 阶段：提交反馈。useless 必须先选二级原因（避免无效请求）
async function submitFeedback(rating: FeedbackRating, uselessReason?: UselessReason) {
  if (!props.message.query_log_id || feedbackState.value !== null) return
  if (rating === 'useless' && !uselessReason) {
    showUselessReasons.value = true
    return
  }
  try {
    await putFeedback({
      query_log_id: props.message.query_log_id,
      rating,
      useless_reason: uselessReason,
    })
    feedbackState.value = rating
    showUselessReasons.value = false
  } catch {
    // 失败静默，不阻塞用户
  }
}
</script>

<template>
  <div class="group flex justify-start gap-3 py-3">
    <!-- AI 头像 -->
    <div class="shrink-0 w-7 h-7 rounded-full bg-stone-800 flex items-center justify-center">
      <svg width="16" height="16" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="16" r="8" class="fill-white/90" />
        <circle cx="20" cy="16" r="8" class="fill-amber-400/80 mix-blend-multiply" />
        <circle cx="16" cy="22" r="6" class="fill-white/40 mix-blend-multiply" />
      </svg>
    </div>

    <div class="flex min-w-0 flex-col gap-1 max-w-[80%]">
      <!-- 思考过程可视化：流式期间实时展开，完成后折叠（历史消息无 trace 不渲染） -->
      <TraceTimeline
        v-if="message.trace && message.trace.length"
        :trace="message.trace"
        :streaming="!!message.isStreaming"
        :duration-ms="message.traceDurationMs"
      />

      <!-- 阶段 2：只展示后端给出的安全判断，不在前端根据正文自行推断风险。 -->
      <div
        v-if="showSafetyNotice"
        class="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900"
        data-testid="safety-notice"
      >
        <ShieldAlert class="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
        <div class="min-w-0">
          <div class="font-semibold">安全提醒 · {{ safetyLevelLabel }}</div>
          <div v-if="safetySituationLabel" class="mt-0.5 text-red-800">设备状态：{{ safetySituationLabel }}</div>
          <div class="mt-0.5">请先停止高风险操作，按回答中的安全建议处理。</div>
          <div v-if="message.escalation_required" class="mt-1 flex items-start gap-1 font-medium">
            <Headset class="mt-0.5 h-3.5 w-3.5 shrink-0" />
            建议联系人工或官方售后支持，当前问题需要进一步确认。
          </div>
          <button
            v-if="message.escalation_required && conversationId"
            class="mt-1.5 flex items-center gap-1 rounded-md border border-red-300 bg-white px-2 py-1 font-medium text-red-700 transition-colors hover:bg-red-100"
            data-testid="open-ticket-draft"
            @click="showTicketDraft = true"
          >
            <Ticket class="h-3.5 w-3.5" />
            生成售后工单
          </button>
        </div>
      </div>

      <div
        v-else-if="message.escalation_required"
        class="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
        data-testid="escalation-notice"
      >
        <Headset class="h-4 w-4 shrink-0 text-amber-600" />
        建议联系人工或官方售后支持，当前问题需要进一步确认。
        <button
          v-if="conversationId"
          class="flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-1 font-medium text-amber-800 transition-colors hover:bg-amber-100"
          data-testid="open-ticket-draft"
          @click="showTicketDraft = true"
        >
          <Ticket class="h-3.5 w-3.5" />
          生成售后工单
        </button>
      </div>

      <!-- 阶段 5：Agent 已自动创建工单草稿（草稿不提交，用户确认后进入管理端） -->
      <div
        v-if="agentTicket"
        class="flex flex-wrap items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900"
        data-testid="agent-ticket-notice"
      >
        <Ticket class="h-4 w-4 shrink-0 text-sky-600" />
        <span>
          已为你生成售后工单草稿 <span class="font-semibold">{{ agentTicket.ticket_number }}</span>
          （{{ agentTicket.status === 'draft' ? '待你确认提交' : agentTicket.status }}）。
        </span>
        <button
          class="flex items-center gap-1 rounded-md border border-sky-300 bg-white px-2 py-1 font-medium text-sky-800 transition-colors hover:bg-sky-100"
          data-testid="view-agent-ticket"
          @click="openAgentTicket"
        >
          查看工单
        </button>
      </div>

      <TicketDraftModal
        :open="showTicketDraft"
        :conversation-id="conversationId || null"
        @close="showTicketDraft = false"
      />

      <div v-if="intentLabel" class="flex items-center gap-2 text-[11px] text-gray-500" data-testid="intent-label">
        <span class="rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5">问题类型：{{ intentLabel }}</span>
      </div>

      <div
        v-if="attachmentStatusLabel"
        class="flex items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900"
        data-testid="attachment-status"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-sky-500" :class="message.attachment_status?.status === 'started' ? 'animate-pulse' : ''"></span>
        {{ attachmentStatusLabel }}
      </div>

      <!-- P1-3: 质量警告横幅（仅 quality_fail 路径展示） -->
      <div
        v-if="message.quality_warning"
        class="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5"
      >
        {{ message.quality_warning }}
      </div>

      <!-- 内容 -->
      <div class="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
        <MarkdownRenderer v-if="displayContent" :content="displayContent" />
        <span
          v-else-if="message.isStreaming"
          class="inline-block w-2 h-4 bg-stone-400 animate-pulse align-middle"
        ></span>
        <span v-else class="text-gray-400 text-sm italic">（无内容）</span>

        <!-- 流式时光标 -->
        <span
          v-if="message.isStreaming && displayContent"
          class="inline-block w-2 h-4 bg-stone-400 animate-pulse align-middle ml-0.5"
        ></span>
      </div>

      <!-- 操作菜单 -->
      <div
        class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity px-1"
      >
        <button
          @click="copyContent(displayContent)"
          class="flex items-center gap-1 text-[11px] text-gray-500 hover:text-stone-700 px-1.5 py-0.5 rounded hover:bg-gray-100 transition-colors"
        >
          <Check v-if="copied" class="w-3 h-3" />
          <Copy v-else class="w-3 h-3" />
          {{ copied ? '已复制' : '复制' }}
        </button>
        <button
          v-if="!message.isStreaming"
          @click="regenerate"
          class="flex items-center gap-1 text-[11px] text-gray-500 hover:text-stone-700 px-1.5 py-0.5 rounded hover:bg-gray-100 transition-colors"
        >
          <RefreshCw class="w-3 h-3" />
          重新生成
        </button>
      </div>

      <!-- 第 2 阶段：反馈按钮区（非流式且已绑定 query_log_id 时展示） -->
      <div
        v-if="!message.isStreaming && message.query_log_id"
        class="flex items-center gap-1 flex-wrap px-1"
      >
        <!-- 👍 有帮助 -->
        <button
          @click="submitFeedback('useful')"
          :disabled="feedbackState !== null"
          class="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded transition-colors disabled:cursor-default"
          :class="feedbackState === 'useful'
            ? 'text-green-600 bg-green-50'
            : 'text-gray-500 hover:text-stone-700 hover:bg-gray-100 disabled:hover:text-gray-500 disabled:hover:bg-transparent'"
        >
          <ThumbsUp class="w-3 h-3" /> 有帮助
        </button>
        <!-- 👎 无帮助 -->
        <button
          @click="submitFeedback('useless')"
          :disabled="feedbackState !== null"
          class="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded transition-colors disabled:cursor-default"
          :class="feedbackState === 'useless'
            ? 'text-red-600 bg-red-50'
            : 'text-gray-500 hover:text-stone-700 hover:bg-gray-100 disabled:hover:text-gray-500 disabled:hover:bg-transparent'"
        >
          <ThumbsDown class="w-3 h-3" /> 无帮助
        </button>
        <!-- 🐛 错误 -->
        <button
          @click="submitFeedback('bug')"
          :disabled="feedbackState !== null"
          class="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded transition-colors disabled:cursor-default"
          :class="feedbackState === 'bug'
            ? 'text-amber-600 bg-amber-50'
            : 'text-gray-500 hover:text-stone-700 hover:bg-gray-100 disabled:hover:text-gray-500 disabled:hover:bg-transparent'"
        >
          <Bug class="w-3 h-3" /> 错误
        </button>

        <!-- 二级原因选择（仅 useless 展开时） -->
        <div v-if="showUselessReasons" class="flex items-center gap-1 ml-2">
          <button
            v-for="r in uselessReasonOptions"
            :key="r.value"
            @click="submitFeedback('useless', r.value)"
            class="text-[11px] px-1.5 py-0.5 rounded text-gray-600 hover:text-red-700 hover:bg-red-50 border border-gray-200"
          >
            {{ r.label }}
          </button>
        </div>
      </div>

      <!-- 引用来源 -->
      <div v-if="message.sources && message.sources.length" class="mt-1 space-y-1.5">
        <div class="text-xs text-gray-500 font-medium">引用来源</div>
        <SourceCard v-for="(s, i) in message.sources" :key="i" :source="s" :index="i" />
      </div>

      <!-- 评估标签 -->
      <JudgeBadges :route-path="message.route_path" :judge-log="message.judge_log" />
    </div>
  </div>
</template>
