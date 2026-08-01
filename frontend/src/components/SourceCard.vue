<!-- frontend/src/components/SourceCard.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Source } from '@/types'
import { FileText, Globe, ExternalLink, ChevronDown, ChevronUp } from 'lucide-vue-next'

const props = defineProps<{ source: Source; index?: number }>()

const expanded = ref(false)

const isUrl = computed(() => {
  try {
    new URL(props.source.source)
    return true
  } catch {
    return false
  }
})

function onCardClick() {
  if (isUrl.value) {
    window.open(props.source.source, '_blank', 'noopener,noreferrer')
  } else {
    expanded.value = !expanded.value
  }
}
</script>

<template>
  <div
    @click="onCardClick"
    :class="[
      'border rounded-lg p-3 transition-all cursor-pointer group',
      expanded && !isUrl
        ? 'bg-white border-stone-300 shadow-sm'
        : 'bg-stone-50/60 border-gray-200 hover:bg-white hover:border-stone-300 hover:shadow-sm',
    ]"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="flex items-start gap-2 min-w-0 flex-1">
        <div
          class="shrink-0 w-5 h-5 rounded flex items-center justify-center mt-0.5"
          :class="isUrl ? 'bg-amber-100 text-amber-700' : 'bg-stone-200 text-stone-700'"
        >
          <Globe v-if="isUrl" class="w-3 h-3" />
          <FileText v-else class="w-3 h-3" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium text-stone-800 truncate">
            <span v-if="index !== undefined" class="text-amber-700 mr-1">[{{ index + 1 }}]</span>
            {{ source.title || source.source }}
          </div>
          <div class="text-xs text-gray-500 truncate mt-0.5">{{ source.source }}</div>
        </div>
      </div>
      <div class="shrink-0 mt-0.5">
        <ExternalLink
          v-if="isUrl"
          class="w-3.5 h-3.5 text-gray-400 group-hover:text-amber-600 transition-colors"
        />
        <ChevronUp
          v-else-if="expanded"
          class="w-4 h-4 text-gray-400 group-hover:text-stone-700 transition-colors"
        />
        <ChevronDown
          v-else
          class="w-4 h-4 text-gray-400 group-hover:text-stone-700 transition-colors"
        />
      </div>
    </div>

    <div
      :class="[
        'mt-2 text-sm text-stone-700 leading-relaxed',
        !isUrl && expanded ? '' : 'line-clamp-2',
      ]"
    >
      {{ source.content }}
    </div>
  </div>
</template>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
