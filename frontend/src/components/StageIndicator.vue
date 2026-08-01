<!-- frontend/src/components/StageIndicator.vue -->
<script setup lang="ts">
defineProps<{ stage?: string }>()

// 与 backend/app/api/chat.py 中 STAGE_LABELS 保持顺序一致
const stages = [
  '正在理解问题...',
  '正在分析问题结构...',
  '正在进行多步推理...',
  '正在判断问题类型...',
  '正在检索知识库...',
  '正在联网搜索...',
  '正在尝试联网搜索...',
  '正在生成回答...',
  '正在评估答案质量...',
]

function stageIndex(stage?: string): number {
  if (!stage) return -1
  return stages.indexOf(stage)
}
</script>

<template>
  <div v-if="stage" class="flex items-center gap-3 text-sm text-gray-500 py-1">
    <div class="flex items-center gap-1.5">
      <span
        v-for="(s, i) in stages"
        :key="s"
        :class="[
          'w-2 h-2 rounded-full transition-all duration-300',
          i <= stageIndex(stage) ? 'bg-amber-500' : 'bg-gray-200',
          i === stageIndex(stage) ? 'ring-2 ring-amber-200 scale-110' : '',
        ]"
        :title="s"
      ></span>
    </div>
    <span class="text-xs text-gray-500">{{ stage }}</span>
  </div>
</template>
