<!-- frontend/src/components/JudgeBadges.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import { ChevronDown, ChevronUp } from 'lucide-vue-next'
import type { JudgeResult } from '@/types'

const props = defineProps<{
  routePath?: string
  judgeLog?: JudgeResult[]
}>()

const expanded = ref(false)

const routeLabels: Record<string, string> = {
  local: '知识库',
  online: '联网搜索',
  decomposition: '多步推理',
  fallback: '降级联网',
}

const routeLabel = computed(() =>
  props.routePath ? routeLabels[props.routePath] ?? props.routePath : ''
)

const displayJudges = computed(() => props.judgeLog ?? [])

// 后端语义：
// is_hallucination: passed=True 表示有幻觉（坏），passed=False 表示无幻觉（好）
// is_quality_pass:  passed=True 表示质量通过（好），passed=False 表示不通过（坏）
// is_relevant:      passed=True 表示相关（好）
function judgeColor(j: JudgeResult): string {
  if (j.judge_type === 'is_hallucination') {
    return j.passed
      ? 'bg-red-50 text-red-700 border-red-100'
      : 'bg-green-50 text-green-700 border-green-100'
  }
  if (j.judge_type === 'is_quality_pass') {
    return j.passed
      ? 'bg-green-50 text-green-700 border-green-100'
      : 'bg-amber-50 text-amber-700 border-amber-100'
  }
  return 'bg-stone-100 text-stone-700 border-stone-200'
}

function judgeLabel(j: JudgeResult): string {
  const map: Record<string, (j: JudgeResult) => string> = {
    is_relevant: () => '相关',
    is_quality_pass: (jj) => (jj.passed ? '质量通过' : '质量未通过'),
    is_hallucination: (jj) => (jj.passed ? '疑似幻觉' : '无幻觉'),
    fallback: () => '降级',
  }
  const v = map[j.judge_type]
  return v ? v(j) : j.judge_type
}
</script>

<template>
  <div v-if="routeLabel || displayJudges.length" class="mt-1.5">
    <div class="flex flex-wrap items-center gap-2">
      <span
        v-if="routeLabel"
        class="px-2 py-0.5 text-[11px] rounded-full bg-stone-100 text-stone-700 border border-stone-200 font-medium"
      >
        {{ routeLabel }}
      </span>
      <button
        v-if="displayJudges.length"
        @click="expanded = !expanded"
        class="flex items-center gap-0.5 text-[11px] text-gray-500 hover:text-stone-700 px-1.5 py-0.5 rounded hover:bg-gray-100 transition-colors"
      >
        评估详情
        <ChevronDown v-if="!expanded" class="w-3 h-3" />
        <ChevronUp v-else class="w-3 h-3" />
      </button>
    </div>

    <div
      v-if="expanded && displayJudges.length"
      class="mt-1.5 flex flex-wrap gap-1.5 animate-fade-in"
    >
      <span
        v-for="(j, i) in displayJudges"
        :key="i"
        class="px-2 py-0.5 text-[11px] rounded-full font-medium border"
        :class="judgeColor(j)"
        :title="j.reason"
      >
        {{ judgeLabel(j) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
@keyframes fade-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in {
  animation: fade-in 0.2s ease-out both;
}
</style>
