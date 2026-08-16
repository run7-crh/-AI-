<!-- frontend/src/components/TraceTimeline.vue -->
<!-- 思考过程可视化：流式期间垂直 timeline 逐节点点亮；完成后折叠为"已深度思考"摘要行。
     设计依据：docs/superpowers/specs/2026-08-16-trace-visualization-design.md -->
<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { TraceNode } from '@/types'
import { Loader2, Check, X, ChevronRight } from 'lucide-vue-next'

const props = defineProps<{
  trace: TraceNode[]
  streaming: boolean
  durationMs?: number
}>()

// 完成后默认折叠；重新进入流式时自动展开
const collapsed = ref(false)
watch(
  () => props.streaming,
  (v) => { collapsed.value = !v },
  { immediate: true }
)

// 各节点行的展开状态（下标为 key，CRAG 回路同名节点独立展开）
const expandedRows = ref<Set<number>>(new Set())
function toggleRow(i: number): void {
  if (expandedRows.value.has(i)) expandedRows.value.delete(i)
  else expandedRows.value.add(i)
}
function hasDetail(n: TraceNode): boolean {
  return Boolean(n.reasoning || (n.output && Object.keys(n.output).length > 0))
}

// reasoning 展开区自动滚动到底（思维流实时 append）
const reasoningEls = ref<Record<number, HTMLElement | null>>({})
watch(
  () => props.trace.map((t) => t.reasoning?.length ?? 0).join(','),
  async () => {
    await nextTick()
    for (const el of Object.values(reasoningEls.value)) {
      if (el) el.scrollTop = el.scrollHeight
    }
  }
)

function formatMs(ms?: number): string {
  if (ms === undefined) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

// output 字段的中文标签（与后端 TRACE_OUTPUT_FIELDS 白名单字段对齐）
const FIELD_LABELS: Record<string, string> = {
  rewritten_query: '改写后的问题',
  is_chitchat: '闲聊问题',
  needs_decomposition: '需要分解',
  reasoning_steps: '子问题',
  is_relevant: '知识库相关',
  retrieval_result: '检索到的文档',
  avg_reranker_score: '重排均分',
  rag_quality_pass: '检索质量通过',
  correction_count: '纠正次数',
  web_search_result: '联网搜索结果',
  has_hallucination: '疑似幻觉',
  answer_quality_pass: '答案质量通过',
  quality_warning: '质量警告',
  judge_log: '判断依据',
}

interface OutputRow {
  label: string
  text?: string
  bool?: boolean
  number?: number
  docs?: { title: string; score?: number; content: string }[]
  steps?: string[]
}

function outputRows(n: TraceNode): OutputRow[] {
  const rows: OutputRow[] = []
  for (const [key, value] of Object.entries(n.output ?? {})) {
    const label = FIELD_LABELS[key] ?? key
    if (key === 'retrieval_result' || key === 'web_search_result') {
      rows.push({
        label,
        docs: (value as Array<Record<string, unknown>>).map((d) => ({
          title: String(d.title ?? d.source ?? '未知来源'),
          score: typeof d.score === 'number' ? d.score : undefined,
          content: String(d.content ?? ''),
        })),
      })
    } else if (key === 'reasoning_steps') {
      rows.push({ label, steps: (value as unknown[]).map(String) })
    } else if (typeof value === 'boolean') {
      rows.push({ label, bool: value })
    } else if (key === 'judge_log') {
      const j = value as { raw_output?: { reason?: string }; judge_type?: string }
      rows.push({ label, text: j?.raw_output?.reason ?? j?.judge_type ?? '' })
    } else if (typeof value === 'number') {
      rows.push({ label, number: value })
    } else {
      rows.push({ label, text: String(value) })
    }
  }
  return rows
}
</script>

<template>
  <div class="text-sm py-1">
    <!-- 折叠态摘要行（完成后） -->
    <button
      v-if="collapsed"
      @click="collapsed = false"
      class="flex items-center gap-1.5 text-xs text-gray-500 hover:text-stone-700 transition-colors"
    >
      <span class="w-4 h-4 rounded-full bg-stone-100 flex items-center justify-center">
        <ChevronRight class="w-3 h-3" />
      </span>
      已深度思考<template v-if="durationMs !== undefined">（用时 {{ (durationMs / 1000).toFixed(1) }}s · {{ trace.length }} 个节点）</template>
    </button>

    <!-- 展开态 timeline -->
    <div v-else class="space-y-0.5">
      <button
        v-if="!streaming"
        @click="collapsed = true"
        class="text-xs text-gray-400 hover:text-stone-700 transition-colors"
      >
        收起思考过程
      </button>
      <TransitionGroup name="trace" tag="div" class="space-y-0.5">
        <div v-for="(node, i) in trace" :key="`${node.node}-${i}`">
          <!-- 节点行 -->
          <button
            @click="hasDetail(node) && toggleRow(i)"
            class="flex items-center gap-2 w-full text-left px-1 py-0.5 rounded hover:bg-gray-50 transition-colors"
            :class="hasDetail(node) ? 'cursor-pointer' : 'cursor-default'"
          >
            <span class="w-4 h-4 shrink-0 flex items-center justify-center">
              <Loader2 v-if="node.status === 'running'" class="w-3 h-3 animate-spin text-amber-500" />
              <Check v-else-if="node.status === 'done'" class="w-3 h-3 text-green-600" />
              <X v-else class="w-3 h-3 text-red-500" />
            </span>
            <span class="text-xs" :class="node.status === 'running' ? 'text-stone-700 font-medium' : 'text-gray-500'">
              {{ node.label }}
            </span>
            <span v-if="node.durationMs !== undefined" class="text-[10px] text-gray-400">
              {{ formatMs(node.durationMs) }}
            </span>
            <ChevronRight
              v-if="hasDetail(node)"
              class="w-3 h-3 text-gray-400 transition-transform"
              :class="expandedRows.has(i) ? 'rotate-90' : ''"
            />
          </button>

          <!-- 展开区：reasoning 思维流 + output 中间结果 -->
          <div v-if="expandedRows.has(i)" class="ml-6 mt-0.5 border-l-2 border-gray-100 pl-3 space-y-2 pb-1">
            <div
              v-if="node.reasoning"
              :ref="(el) => (reasoningEls[i] = el as HTMLElement | null)"
              class="max-h-48 overflow-y-auto text-xs text-gray-500 font-mono leading-relaxed whitespace-pre-wrap bg-gray-50 rounded-md p-2"
            >
              {{ node.reasoning }}
            </div>
            <div v-for="row in outputRows(node)" :key="row.label" class="text-xs text-gray-600">
              <span class="text-gray-400">{{ row.label }}：</span>
              <span v-if="row.bool !== undefined" :class="row.bool ? 'text-green-600' : 'text-red-500'">
                {{ row.bool ? '是' : '否' }}
              </span>
              <span v-else-if="row.number !== undefined" class="tabular-nums">{{ row.number.toFixed(4) }}</span>
              <span v-else-if="row.text">{{ row.text }}</span>
              <ol v-else-if="row.steps" class="list-decimal ml-4 space-y-0.5">
                <li v-for="(s, j) in row.steps" :key="j">{{ s }}</li>
              </ol>
              <div v-else-if="row.docs" class="space-y-1 mt-1">
                <div v-for="(d, j) in row.docs" :key="j" class="bg-gray-50 rounded-md p-1.5">
                  <div class="flex items-center justify-between gap-2">
                    <span class="font-medium text-gray-700 truncate">{{ d.title }}</span>
                    <span v-if="d.score !== undefined" class="text-[10px] text-gray-400 shrink-0">
                      {{ d.score.toFixed(3) }}
                    </span>
                  </div>
                  <p class="text-gray-500 line-clamp-3">{{ d.content }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
/* 节点行进入动画（Tailwind transition 不覆盖列表项） */
.trace-enter-active {
  transition: all 0.3s ease;
}
.trace-enter-from {
  opacity: 0;
  transform: translateX(-8px);
}
</style>
