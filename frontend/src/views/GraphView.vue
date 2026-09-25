<!-- frontend/src/views/GraphView.vue -->
<!-- 知识图谱页：力导向图 + 侧边概念卡片 + 一键提问闭环。
     设计依据：docs/superpowers/specs/2026-08-16-knowledge-graph-design.md -->
<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ArrowLeft, RefreshCw, Send, X } from 'lucide-vue-next'
import { fetchGraph, rebuildIndex, GraphNotBuiltError } from '@/api/graph'
import { buildGraphOption, CATEGORY_COLORS, OTHER_CATEGORY, OTHER_COLOR } from '@/utils/graphOption'
import type { GraphData, GraphNode } from '@/types'
import { useAuthStore } from '@/stores/auth'

echarts.use([GraphChart, TooltipComponent, CanvasRenderer])

const router = useRouter()
const auth = useAuthStore()

const loading = ref(true)
const notBuilt = ref(false)
const loadError = ref('')
const rebuilding = ref(false)
const data = ref<GraphData | null>(null)
const selected = ref<GraphNode | null>(null)
const visibleCategories = ref<Set<string>>(new Set(Object.keys(CATEGORY_COLORS)))

const containerRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let resizeFrame: number | null = null

function normalizeCategory(category: string): string {
  return Object.prototype.hasOwnProperty.call(CATEGORY_COLORS, category) ? category : OTHER_CATEGORY
}

function categoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? OTHER_COLOR
}

const legendCategories = computed(() => {
  const names = Object.keys(CATEGORY_COLORS)
  const hasOther = Boolean(data.value?.nodes.some((node) => !names.includes(node.category)))
  return hasOther ? [...names, OTHER_CATEGORY] : names
})

const hasVisibleNodes = computed(() => {
  if (!data.value) return false
  return data.value.nodes.some((node) => visibleCategories.value.has(normalizeCategory(node.category)))
})

/** 选中概念的相邻概念（含关系类型），供卡片列表点击切换 */
const neighbors = computed(() => {
  if (!data.value || !selected.value) return [] as { node: GraphNode; type: string }[]
  const byId = new Map(data.value.nodes.map((n) => [n.id, n]))
  const sid = selected.value.id
  return data.value.edges
    .filter((e) => e.source === sid || e.target === sid)
    .map((e) => {
      const otherId = e.source === sid ? e.target : e.source
      return { node: byId.get(otherId), type: e.type }
    })
    .filter((x): x is { node: GraphNode; type: string } => Boolean(x.node))
})

async function load(): Promise<void> {
  loading.value = true
  notBuilt.value = false
  loadError.value = ''
  try {
    data.value = await fetchGraph()
    visibleCategories.value = new Set(legendCategories.value)
    renderChart()
  } catch (e) {
    if (e instanceof GraphNotBuiltError) notBuilt.value = true
    else loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function renderChart(): void {
  if (!containerRef.value || !data.value) return
  if (!chart) {
    chart = echarts.init(containerRef.value)
    chart.on('click', (params) => {
      if (params.dataType === 'node') {
        selected.value =
          data.value?.nodes.find((n) => n.id === (params.data as { id?: string }).id) ?? null
      }
    })
  }
  chart.setOption(buildGraphOption(data.value, visibleCategories.value))
}

function toggleCategory(category: string): void {
  const next = new Set(visibleCategories.value)
  if (next.has(category)) next.delete(category)
  else next.add(category)
  visibleCategories.value = next
  if (selected.value && !next.has(normalizeCategory(selected.value.category))) selected.value = null
  renderChart()
}

async function onRebuild(): Promise<void> {
  rebuilding.value = true
  try {
    const r = await rebuildIndex()
    if (!r.graph_built) loadError.value = '图谱构建未完成，请稍后重试'
    await load()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    rebuilding.value = false
  }
}

function focusNeighbor(n: GraphNode): void {
  selected.value = n
}

function askAgent(n: GraphNode): void {
  const aliases = n.aliases?.length ? `（${n.aliases.join('、')}）` : ''
  router.push({ path: '/chat', query: { ask: `详细介绍「${n.title}」${aliases}` } })
}

onMounted(() => {
  load()
  if (containerRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (resizeFrame !== null) return
      resizeFrame = requestAnimationFrame(() => {
        resizeFrame = null
        chart?.resize()
      })
    })
    resizeObserver.observe(containerRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  if (resizeFrame !== null) cancelAnimationFrame(resizeFrame)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="flex flex-col h-full w-full bg-stone-50">
    <!-- 顶栏 -->
    <header class="h-14 border-b border-gray-200/80 bg-white/90 backdrop-blur flex items-center gap-3 px-4 shrink-0">
      <button
        @click="router.push('/chat')"
        class="flex items-center gap-1.5 text-xs text-gray-500 hover:text-stone-800 transition-colors"
      >
        <ArrowLeft class="w-3.5 h-3.5" /> 返回对话
      </button>
      <h1 class="text-sm font-semibold text-stone-800">知识图谱</h1>
      <span v-if="data" class="text-xs text-gray-400">
        {{ data.nodes.length }} 个概念 · {{ data.edges.length }} 条关系
      </span>
      <span v-if="data && data.edges.length === 0" class="text-[10px] text-amber-600">
        当前暂无关系，可能需要重建知识图谱数据
      </span>
    </header>

    <div class="flex-1 flex min-h-0">
      <main class="flex-1 min-w-0 min-h-0 flex flex-col">
        <div v-if="data" class="shrink-0 border-b border-gray-200/80 bg-white px-4 py-2 space-y-1.5">
          <span class="text-[10px] font-medium text-gray-400 uppercase tracking-wide">按类别筛选</span>
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              v-for="category in legendCategories"
              :key="category"
              type="button"
              :aria-pressed="visibleCategories.has(category)"
              @click="toggleCategory(category)"
              class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors"
              :class="visibleCategories.has(category) ? 'border-gray-200 bg-white text-stone-700' : 'border-gray-100 bg-gray-50 text-gray-400'"
            >
              <span
                class="h-2 w-2 rounded-full"
                :style="{ backgroundColor: categoryColor(category), opacity: visibleCategories.has(category) ? 1 : 0.35 }"
              />
              {{ category }}
            </button>
          </div>
        </div>

        <div class="relative flex-1 min-h-0">
          <!-- 图谱画布 -->
          <div ref="containerRef" class="absolute inset-0" />

          <!-- 加载 / 空态 / 错误 -->
          <div
            v-if="loading || notBuilt || loadError"
            class="absolute inset-0 flex items-center justify-center bg-stone-50/80 z-10"
          >
            <div v-if="loading" class="text-sm text-gray-400">图谱加载中...</div>
            <div v-else-if="notBuilt" class="text-center space-y-3">
              <p class="text-sm text-gray-500">知识图谱尚未构建</p>
              <p class="text-xs text-gray-400">重建知识库索引后将自动生成概念关系图谱</p>
              <button
                v-if="auth.isAdmin"
                @click="onRebuild"
                :disabled="rebuilding"
                class="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-stone-800 text-white text-xs font-medium hover:bg-stone-700 disabled:opacity-50 transition-colors"
              >
                <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': rebuilding }" />
                {{ rebuilding ? '重建中（含 18 次 LLM 抽取，约 1-2 分钟）' : '重建知识库' }}
              </button>
              <p v-else class="text-xs text-gray-400">请联系管理员构建知识图谱</p>
            </div>
            <div v-else class="text-center space-y-2">
              <p class="text-sm text-red-500">{{ loadError }}</p>
              <button @click="load" class="text-xs text-gray-500 hover:text-stone-800">重试</button>
            </div>
          </div>

          <div v-else-if="data && !hasVisibleNodes" class="absolute inset-0 flex items-center justify-center pointer-events-none">
            <p class="rounded-lg bg-white/90 px-3 py-2 text-xs text-gray-500 shadow-sm">请至少开启一个类别</p>
          </div>
        </div>
      </main>

      <!-- 侧边概念卡片 -->
      <Transition
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="translate-x-full"
        leave-active-class="transition duration-150 ease-in"
        leave-to-class="translate-x-full"
      >
        <aside
          v-if="selected"
          class="w-72 shrink-0 border-l border-gray-200 bg-white p-4 space-y-3 overflow-y-auto"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <h2 class="text-sm font-semibold text-stone-800">{{ selected.title }}</h2>
              <span
                class="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] text-white"
                :style="{ backgroundColor: CATEGORY_COLORS[selected.category] ?? '#a8a29e' }"
              >
                {{ selected.category }}
              </span>
            </div>
            <button @click="selected = null" class="text-gray-400 hover:text-stone-700">
              <X class="w-4 h-4" />
            </button>
          </div>

          <p v-if="selected.summary" class="text-xs text-gray-600 leading-relaxed">
            {{ selected.summary }}
          </p>
          <div v-else class="flex flex-wrap gap-1">
            <span
              v-for="t in selected.tags"
              :key="t"
              class="px-1.5 py-0.5 rounded bg-stone-100 text-stone-600 text-[10px]"
            >
              {{ t }}
            </span>
          </div>

          <div v-if="neighbors.length" class="space-y-1.5">
            <h3 class="text-[10px] font-medium text-gray-400 uppercase tracking-wide">相邻概念</h3>
            <button
              v-for="nb in neighbors"
              :key="nb.node.id"
              @click="focusNeighbor(nb.node)"
              class="flex items-center justify-between w-full px-2 py-1.5 rounded-md hover:bg-stone-50 text-left transition-colors"
            >
              <span class="text-xs text-gray-700 truncate">{{ nb.node.title }}</span>
              <span class="text-[10px] text-gray-400 shrink-0 ml-2">{{ nb.type }}</span>
            </button>
          </div>

          <div class="pt-2 border-t border-gray-100 space-y-2">
            <button
              @click="askAgent(selected)"
              class="flex items-center justify-center gap-1.5 w-full px-3 py-2 rounded-lg bg-amber-600 text-white text-xs font-medium hover:bg-amber-700 transition-colors"
            >
              <Send class="w-3.5 h-3.5" /> 向 Agent 提问
            </button>
            <p class="text-[10px] text-gray-400 text-center">来源：{{ selected.file }}</p>
          </div>
        </aside>
      </Transition>
    </div>
  </div>
</template>
