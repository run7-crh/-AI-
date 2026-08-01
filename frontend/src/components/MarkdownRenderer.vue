<!-- frontend/src/components/MarkdownRenderer.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

const props = defineProps<{ content: string }>()

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function highlightCode(str: string, lang: string): string {
  if (lang && hljs.getLanguage(lang)) {
    try {
      return `<pre class="hljs"><code>${hljs.highlight(str, { language: lang }).value}</code></pre>`
    } catch {
      // fallthrough
    }
  }
  return `<pre class="hljs"><code>${escapeHtml(str)}</code></pre>`
}

const md: MarkdownIt = new MarkdownIt({
  html: false, // 关键：禁用 HTML 防 XSS
  linkify: true,
  breaks: false,
  highlight: highlightCode,
})

const html = computed(() => md.render(props.content || ''))
</script>

<template>
  <div class="markdown-body" v-html="html"></div>
</template>

<style scoped>
.markdown-body {
  line-height: 1.75;
  word-break: break-word;
  color: #292524;
}
.markdown-body :deep(p) { margin: 0.5em 0; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  font-weight: 600;
  margin: 0.9em 0 0.45em;
  color: #1c1917;
}
.markdown-body :deep(h1) { font-size: 1.35em; }
.markdown-body :deep(h2) { font-size: 1.15em; }
.markdown-body :deep(h3) { font-size: 1.05em; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { padding-left: 1.5em; margin: 0.5em 0; }
.markdown-body :deep(li) { margin: 0.25em 0; }
.markdown-body :deep(code):not(.hljs code) {
  background: rgba(41, 37, 36, 0.07);
  padding: 0.15em 0.4em;
  border-radius: 6px;
  font-size: 0.875em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace;
  color: #7c2d12;
}
.markdown-body :deep(pre) {
  background: #f6f8fa;
  color: #1f2937;
  padding: 1em 1.1em;
  border-radius: 12px;
  overflow-x: auto;
  margin: 0.75em 0;
  font-size: 0.85em;
  border: 1px solid #e5e7eb;
}
.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
  color: inherit;
  font-size: inherit;
}
.markdown-body :deep(blockquote) {
  border-left: 3px solid #d6d3d1;
  padding-left: 1em;
  color: #57534e;
  margin: 0.6em 0;
}
.markdown-body :deep(a) {
  color: #b45309;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown-body :deep(table) { border-collapse: collapse; margin: 0.6em 0; width: 100%; }
.markdown-body :deep(th),
.markdown-body :deep(td) { border: 1px solid #e7e5e4; padding: 0.4em 0.7em; }
.markdown-body :deep(th) { background: #fafaf9; font-weight: 600; }
</style>
