<!-- frontend/src/components/EmptyState.vue -->
<script setup lang="ts">
import { useChatStore } from '@/stores/chat'

const store = useChatStore()

const suggestions = ['什么是 RAG？', '最新的 LLM 趋势', '比较 RAG 和微调的优劣']

function useSuggestion(text: string) {
  store.inputText = text
}
</script>

<template>
  <div class="flex-1 flex flex-col items-center justify-center text-center px-6 py-12">
    <!-- 品牌图形 Logo -->
    <div class="mb-5 animate-fade-in">
      <svg width="48" height="48" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="16" r="8" class="fill-stone-800/90" />
        <circle cx="20" cy="16" r="8" class="fill-amber-600/85 mix-blend-multiply" />
        <circle cx="16" cy="22" r="6" class="fill-stone-500/60 mix-blend-multiply" />
      </svg>
    </div>

    <h2 class="text-2xl font-semibold text-stone-800 mb-2 tracking-tight">智识助手</h2>
    <p class="text-sm text-gray-500 mb-8 max-w-sm leading-relaxed">
      基于知识库与联网搜索的智能问答，随时为你解答 AI 领域问题。
    </p>

    <!-- 横向建议标签 -->
    <div class="flex flex-wrap items-center justify-center gap-2 max-w-md">
      <button
        v-for="(text, i) in suggestions"
        :key="i"
        @click="useSuggestion(text)"
        class="px-3 py-1.5 text-xs text-gray-600 bg-white border border-gray-200 rounded-full hover:border-stone-400 hover:text-stone-800 hover:shadow-sm transition-all"
      >
        {{ text }}
      </button>
    </div>
  </div>
</template>

<style scoped>
@keyframes fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in {
  animation: fade-in 0.6s ease-out both;
}
</style>
