<!-- frontend/src/components/SourceCard.vue -->
<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Source } from '@/types'
import { FileText, Globe, ExternalLink, ChevronDown, ChevronUp, Paperclip } from 'lucide-vue-next'

const props = defineProps<{ source: Source; index?: number }>()

const expanded = ref(false)
const sourceUrl = computed(() => props.source.url || props.source.source)

const isUrl = computed(() => {
  try {
    const protocol = new URL(sourceUrl.value).protocol
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
})

const documentTypeLabels: Record<string, string> = {
  product: '产品资料',
  products: '产品资料',
  technical: '技术资料',
  troubleshooting: '故障排查',
  sop: 'SOP',
  case: '案例参考',
  cases: '案例参考',
  safety: '安全资料',
  attachment: '附件',
}

const documentTypeLabel = computed(() => {
  const value = props.source.document_type
  return value ? documentTypeLabels[value] || value : ''
})
const sourceTypeLabel = computed(() => {
  if (props.source.source_type === 'local') return '本地知识库'
  if (props.source.source_type === 'web') return '联网资料'
  if (props.source.source_type === 'attachment') return '用户附件'
  return ''
})
const dataTypeLabel = computed(() => {
  if (props.source.data_type === 'factual') return '知识库资料'
  if (props.source.data_type === 'synthetic') return '模拟案例'
  if (props.source.data_type === 'user_upload') return '用户上传资料'
  return ''
})

function hasValue(value: string | number | null | undefined): boolean {
  return value !== null && value !== undefined && String(value).trim() !== ''
}

function onCardClick() {
  if (isUrl.value) {
    window.open(sourceUrl.value, '_blank', 'noopener,noreferrer')
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
          :class="isUrl ? 'bg-amber-100 text-amber-700' : source.source_type === 'attachment' ? 'bg-sky-100 text-sky-700' : 'bg-stone-200 text-stone-700'"
        >
          <Globe v-if="isUrl" class="w-3 h-3" />
          <Paperclip v-else-if="source.source_type === 'attachment'" class="w-3 h-3" />
          <FileText v-else class="w-3 h-3" />
        </div>
        <div class="min-w-0 flex-1">
          <div class="text-sm font-medium text-stone-800 truncate">
            <span v-if="index !== undefined" class="text-amber-700 mr-1">[{{ index + 1 }}]</span>
            {{ source.title || source.source }}
          </div>
          <div class="text-xs text-gray-500 truncate mt-0.5">{{ source.url || source.source }}</div>
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

    <div v-if="documentTypeLabel || sourceTypeLabel || dataTypeLabel || hasValue(source.product_model) || hasValue(source.component) || hasValue(source.fault_type) || hasValue(source.document_id) || hasValue(source.source_id) || source.score !== null && source.score !== undefined" class="mt-2 flex flex-wrap gap-1.5 break-all text-[10px] text-gray-600" data-testid="source-metadata">
      <span v-if="sourceTypeLabel" class="rounded-full bg-stone-100 px-2 py-0.5">{{ sourceTypeLabel }}</span>
      <span v-if="dataTypeLabel" class="rounded-full px-2 py-0.5" :class="source.data_type === 'synthetic' ? 'bg-amber-100 text-amber-800' : 'bg-green-50 text-green-700'">{{ dataTypeLabel }}</span>
      <span v-if="documentTypeLabel" class="rounded-full px-2 py-0.5" :class="source.document_type === 'safety' ? 'bg-red-50 text-red-700' : 'bg-stone-100'">
        {{ source.document_type === 'safety' ? '安全资料' : documentTypeLabel }}
      </span>
      <span v-if="hasValue(source.product_model)" class="rounded-full bg-blue-50 px-2 py-0.5 text-blue-700">机型：{{ source.product_model }}</span>
      <span v-if="hasValue(source.component)" class="rounded-full bg-stone-100 px-2 py-0.5">部件：{{ source.component }}</span>
      <span v-if="hasValue(source.fault_type)" class="rounded-full bg-stone-100 px-2 py-0.5">故障：{{ source.fault_type }}</span>
      <span v-if="hasValue(source.document_id)" class="rounded-full bg-stone-100 px-2 py-0.5">文档：{{ source.document_id }}</span>
      <span v-if="hasValue(source.source_id)" class="rounded-full bg-stone-100 px-2 py-0.5">来源编号：{{ source.source_id }}</span>
      <span v-if="source.score !== null && source.score !== undefined" class="rounded-full bg-stone-100 px-2 py-0.5">相关度：{{ source.score.toFixed(3) }}</span>
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
