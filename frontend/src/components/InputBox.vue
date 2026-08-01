<!-- frontend/src/components/InputBox.vue -->
<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import { Send, Square } from 'lucide-vue-next'

const store = useChatStore()
const textareaRef = ref<HTMLTextAreaElement>()

async function autoResize() {
  await nextTick()
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}

async function onInput() {
  await autoResize()
}

async function onKeydown(e: KeyboardEvent) {
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    await send()
  }
}

async function send() {
  if (store.isStreaming) return
  if (!store.inputText.trim()) return
  await store.sendMessage()
  await autoResize()
}

function focus() {
  textareaRef.value?.focus()
}

defineExpose({ focus })
</script>

<template>
  <div class="border-t border-gray-200 bg-white px-4 py-3">
    <div class="flex items-end gap-2 max-w-3xl mx-auto">
      <textarea
        ref="textareaRef"
        v-model="store.inputText"
        @input="onInput"
        @keydown="onKeydown"
        rows="1"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        class="flex-1 resize-none border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-stone-400/50 focus:border-stone-400 max-h-[200px]"
      />
      <button
        v-if="!store.isStreaming"
        @click="send"
        :disabled="!store.inputText.trim()"
        class="shrink-0 w-10 h-10 flex items-center justify-center rounded-xl bg-stone-800 text-white hover:bg-stone-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
        title="发送"
      >
        <Send class="w-4 h-4" />
      </button>
      <button
        v-else
        @click="store.stopStreaming"
        class="shrink-0 w-10 h-10 flex items-center justify-center rounded-xl bg-amber-600 text-white hover:bg-amber-700 transition-colors"
        title="停止生成"
      >
        <Square class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>
