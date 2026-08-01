<!-- frontend/src/components/ConversationSidebar.vue -->
<script setup lang="ts">
import { useChatStore } from '@/stores/chat'
import {
  Plus,
  Trash2,
  PanelLeftClose,
  PanelLeft,
  MessageSquare,
  Loader2,
} from 'lucide-vue-next'
import { ref, computed } from 'vue'

const store = useChatStore()
const confirmingId = ref<string | null>(null)

async function onNew() {
  await store.createNewConversation()
}

function askDelete(id: string, e: Event) {
  e.stopPropagation()
  confirmingId.value = id
}

function cancelDelete() {
  confirmingId.value = null
}

async function confirmDelete(id: string) {
  confirmingId.value = null
  await store.deleteConversation(id)
}

function formatTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function isToday(ts: string): boolean {
  return new Date(ts).toDateString() === new Date().toDateString()
}

function isYesterday(ts: string): boolean {
  const d = new Date(ts)
  const y = new Date()
  y.setDate(y.getDate() - 1)
  return d.toDateString() === y.toDateString()
}

const grouped = computed(() => {
  type Item = (typeof store.conversations)[number]
  const groups: { label: string; items: Item[] }[] = []
  const today: Item[] = []
  const yesterday: Item[] = []
  const earlier: Item[] = []
  for (const c of store.conversations) {
    if (isToday(c.updated_at)) today.push(c)
    else if (isYesterday(c.updated_at)) yesterday.push(c)
    else earlier.push(c)
  }
  if (today.length) groups.push({ label: '今天', items: today })
  if (yesterday.length) groups.push({ label: '昨天', items: yesterday })
  if (earlier.length) groups.push({ label: '更早', items: earlier })
  return groups
})
</script>

<template>
  <aside
    :class="[
      'shrink-0 border-r border-gray-200 bg-gray-50/80 backdrop-blur flex flex-col h-full transition-all duration-300 ease-out',
      store.sidebarCollapsed ? 'w-16' : 'w-64',
    ]"
  >
    <!-- 顶部：新建 + 折叠 -->
    <div class="h-14 border-b border-gray-200 flex items-center justify-between px-3 shrink-0">
      <button
        v-if="!store.sidebarCollapsed"
        @click="onNew"
        class="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-stone-800 text-white text-sm font-medium hover:bg-stone-700 active:scale-[0.98] transition-all"
      >
        <Plus class="w-4 h-4" />
        新建会话
      </button>
      <button
        v-else
        @click="onNew"
        class="w-9 h-9 flex items-center justify-center rounded-lg bg-stone-800 text-white hover:bg-stone-700 active:scale-[0.98] transition-all"
        title="新建会话"
      >
        <Plus class="w-4 h-4" />
      </button>
      <button
        @click="store.sidebarCollapsed = !store.sidebarCollapsed"
        class="ml-2 p-1.5 text-gray-500 hover:text-stone-800 hover:bg-gray-200/70 rounded-md transition-colors"
        :title="store.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
      >
        <PanelLeftClose v-if="!store.sidebarCollapsed" class="w-4 h-4" />
        <PanelLeft v-else class="w-4 h-4" />
      </button>
    </div>

    <!-- 骨架屏 -->
    <div
      v-if="store.isLoadingConversations"
      class="flex-1 overflow-y-auto px-3 py-3 space-y-2"
    >
      <template v-if="!store.sidebarCollapsed">
        <div v-for="i in 4" :key="i" class="space-y-2">
          <div class="h-2.5 w-10 bg-gray-200 rounded animate-pulse"></div>
          <div class="h-12 bg-gray-200 rounded-lg animate-pulse"></div>
        </div>
      </template>
      <template v-else>
        <div v-for="i in 6" :key="i" class="h-10 bg-gray-200 rounded-lg animate-pulse"></div>
      </template>
    </div>

    <!-- 空状态 -->
    <div
      v-else-if="store.conversations.length === 0"
      class="flex-1 flex flex-col items-center justify-center px-4 py-8 text-center"
    >
      <MessageSquare class="w-6 h-6 text-gray-300 mb-2" />
      <span v-if="!store.sidebarCollapsed" class="text-xs text-gray-400">暂无会话</span>
    </div>

    <!-- 会话列表 -->
    <div v-else class="flex-1 overflow-y-auto py-2">
      <!-- 展开状态 -->
      <template v-if="!store.sidebarCollapsed">
        <div v-for="g in grouped" :key="g.label" class="mb-2">
          <div
            class="px-4 py-1.5 text-[11px] font-semibold text-gray-400 uppercase tracking-wider"
          >
            {{ g.label }}
          </div>
          <ul>
            <li
              v-for="c in g.items"
              :key="c.id"
              @click="store.selectConversation(c.id)"
              :class="[
                'group cursor-pointer mx-2 rounded-lg transition-all border-l-0',
                store.currentConversationId === c.id
                  ? 'bg-white shadow-sm ring-1 ring-gray-200'
                  : 'hover:bg-gray-100/80',
                confirmingId === c.id ? 'pb-2' : '',
              ]"
            >
              <div class="flex items-start justify-between gap-2 px-3 pt-2.5">
                <div class="min-w-0 flex-1">
                  <div
                    :class="[
                      'text-sm font-medium truncate',
                      store.currentConversationId === c.id ? 'text-stone-800' : 'text-gray-700',
                    ]"
                  >
                    {{ c.title || '新会话' }}
                  </div>
                  <div class="flex items-center gap-2 mt-0.5 text-xs text-gray-500">
                    <span class="flex items-center gap-0.5">
                      <MessageSquare class="w-3 h-3" />
                      {{ c.message_count }}
                    </span>
                    <span>{{ formatTime(c.updated_at) }}</span>
                    <Loader2
                      v-if="store.isStreaming && store.currentConversationId === c.id"
                      class="w-3 h-3 text-amber-600 animate-spin"
                    />
                  </div>
                </div>
                <button
                  v-if="confirmingId !== c.id"
                  @click="askDelete(c.id, $event)"
                  class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-all p-1 -mr-1 rounded hover:bg-red-50"
                  title="删除"
                >
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>

              <!-- 内联删除确认 -->
              <div v-if="confirmingId === c.id" class="px-3 pt-2">
                <div class="flex items-center justify-between rounded-md bg-red-50 px-2.5 py-1.5">
                  <span class="text-xs text-red-700">确认删除该会话？</span>
                  <div class="flex items-center gap-1.5">
                    <button
                      @click.stop="cancelDelete"
                      class="px-2 py-0.5 text-[11px] text-gray-600 hover:text-gray-800 hover:bg-white rounded transition-colors"
                    >
                      取消
                    </button>
                    <button
                      @click.stop="confirmDelete(c.id)"
                      class="px-2 py-0.5 text-[11px] bg-red-600 text-white hover:bg-red-700 rounded transition-colors"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </div>
            </li>
          </ul>
        </div>
      </template>

      <!-- 折叠状态：仅图标 -->
      <template v-else>
        <ul class="px-1.5 space-y-1">
          <li
            v-for="c in store.conversations"
            :key="c.id"
            @click="store.selectConversation(c.id)"
            :title="c.title || '新会话'"
            :class="[
              'group relative cursor-pointer w-full aspect-square rounded-lg flex flex-col items-center justify-center transition-all',
              store.currentConversationId === c.id
                ? 'bg-white shadow-sm ring-1 ring-gray-200 text-stone-800'
                : 'hover:bg-gray-100/80 text-gray-500',
            ]"
          >
            <template v-if="confirmingId !== c.id">
              <MessageSquare class="w-5 h-5" />
              <span
                v-if="c.message_count > 0"
                class="absolute top-1 right-1 min-w-[14px] h-3.5 px-1 flex items-center justify-center text-[10px] font-medium bg-amber-500 text-white rounded-full"
              >
                {{ c.message_count > 99 ? '99+' : c.message_count }}
              </span>
              <button
                @click="askDelete(c.id, $event)"
                class="absolute bottom-0.5 right-0.5 opacity-0 group-hover:opacity-100 p-0.5 text-gray-400 hover:text-red-500 bg-white rounded hover:bg-red-50 transition-all"
              >
                <Trash2 class="w-3 h-3" />
              </button>
            </template>

            <!-- 折叠状态内联确认 -->
            <template v-else>
              <button
                @click.stop="confirmDelete(c.id)"
                class="px-1.5 py-0.5 text-[10px] bg-red-600 text-white rounded hover:bg-red-700 mb-1"
              >
                删除
              </button>
              <button
                @click.stop="cancelDelete"
                class="px-1.5 py-0.5 text-[10px] text-gray-600 hover:bg-gray-100 rounded"
              >
                取消
              </button>
            </template>
          </li>
        </ul>
      </template>
    </div>
  </aside>
</template>
