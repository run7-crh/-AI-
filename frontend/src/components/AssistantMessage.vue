<!-- frontend/src/components/AssistantMessage.vue -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Message, FeedbackRating, UselessReason } from '@/types'
import { useChatStore } from '@/stores/chat'
import { Copy, Check, RefreshCw, ThumbsUp, ThumbsDown, Bug } from 'lucide-vue-next'
import MarkdownRenderer from './MarkdownRenderer.vue'
import TraceTimeline from './TraceTimeline.vue'
import SourceCard from './SourceCard.vue'
import JudgeBadges from './JudgeBadges.vue'
import { putFeedback } from '@/api/feedback'

const props = defineProps<{ message: Message }>()
const store = useChatStore()
const copied = ref(false)

// 第 2 阶段：反馈状态（已反馈时按钮置灰）
const feedbackState = ref<FeedbackRating | null>(null)
const showUselessReasons = ref(false)
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

    <div class="flex flex-col gap-1 max-w-[80%]">
      <!-- 思考过程可视化：流式期间实时展开，完成后折叠（历史消息无 trace 不渲染） -->
      <TraceTimeline
        v-if="message.trace && message.trace.length"
        :trace="message.trace"
        :streaming="!!message.isStreaming"
        :duration-ms="message.traceDurationMs"
      />

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
