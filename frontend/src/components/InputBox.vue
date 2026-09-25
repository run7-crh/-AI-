<!-- frontend/src/components/InputBox.vue -->
<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useChatStore } from '@/stores/chat'
import { Send, Square, Paperclip, X, Loader2, AlertCircle } from 'lucide-vue-next'

const store = useChatStore()
const textareaRef = ref<HTMLTextAreaElement>()
const fileInputRef = ref<HTMLInputElement>()
const allowedExtensions = ['pdf', 'txt', 'md', 'docx', 'log', 'json', 'csv']

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
  if (!store.canSend) return
  await store.sendMessage()
  await autoResize()
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function isExpired(expiresAt?: string): boolean {
  return !!expiresAt && new Date(expiresAt).getTime() <= Date.now()
}

function statusLabel(status: string, extractionStatus: string, expiresAt?: string): string {
  if (isExpired(expiresAt) && status === 'ready') return '已过期'
  if (status === 'uploading') return '上传中'
  if (extractionStatus === 'failed') return '解析失败'
  if (status === 'failed') return '上传失败'
  if (status === 'expired') return '已过期'
  if (status === 'deleted') return '已删除'
  if (extractionStatus === 'pending') return '解析中'
  return '已就绪'
}

function statusClass(status: string, extractionStatus: string, expiresAt?: string): string {
  if (isExpired(expiresAt) && status === 'ready') return 'text-gray-500 bg-gray-100'
  if (status === 'failed' || extractionStatus === 'failed') return 'text-red-700 bg-red-50'
  if (status === 'expired' || status === 'deleted') return 'text-gray-500 bg-gray-100'
  if (status === 'uploading' || extractionStatus === 'pending') return 'text-amber-700 bg-amber-50'
  return 'text-green-700 bg-green-50'
}

async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  const invalid = files.find((file) => {
    const parts = file.name.split('.')
    const extension = parts.pop()?.toLowerCase() || ''
    return parts.length !== 1 || !allowedExtensions.includes(extension)
  })
  if (invalid) {
    store.error = `不支持的附件类型：${invalid.name}`
    return
  }
  await store.uploadAttachments(files)
}

function focus() {
  textareaRef.value?.focus()
}

defineExpose({ focus })
</script>

<template>
  <div class="border-t border-gray-200 bg-white px-4 py-3">
    <div class="max-w-3xl mx-auto space-y-2">
      <div v-if="store.pendingAttachments.length" class="flex flex-wrap gap-2" data-testid="pending-attachments">
        <div
          v-for="attachment in store.pendingAttachments"
          :key="attachment.id"
          class="min-w-0 max-w-full flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs"
        >
          <Paperclip class="w-3.5 h-3.5 shrink-0 text-stone-500" />
          <span class="min-w-0 max-w-[12rem] truncate" :title="attachment.original_name">{{ attachment.original_name }}</span>
          <span class="shrink-0 text-gray-400">{{ formatSize(attachment.size_bytes) }}</span>
          <span class="shrink-0 rounded-full px-1.5 py-0.5" :class="statusClass(attachment.status, attachment.extraction_status, attachment.expires_at)">
            {{ statusLabel(attachment.status, attachment.extraction_status, attachment.expires_at) }}
          </span>
          <span v-if="attachment.status === 'uploading'" class="shrink-0 text-amber-700">{{ attachment.upload_progress || 0 }}%</span>
          <button
            :data-testid="`remove-attachment-${attachment.id}`"
            @click="store.removeAttachment(attachment.id)"
            class="shrink-0 rounded p-0.5 text-gray-400 hover:bg-gray-200 hover:text-gray-700"
            title="移除附件"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div v-if="store.isUploadingAttachments" class="flex items-center gap-2 text-[11px] text-gray-500" data-testid="attachment-progress">
        <Loader2 class="w-3.5 h-3.5 animate-spin text-amber-600" />
        <span>正在上传附件 {{ store.attachmentUploadProgress }}%</span>
      </div>
      <div v-else-if="store.pendingAttachments.some((a) => a.status === 'failed' || a.status === 'expired' || a.extraction_status === 'failed' || isExpired(a.expires_at))" class="flex items-center gap-1.5 text-[11px] text-red-700">
        <AlertCircle class="w-3.5 h-3.5" />
        <span>{{ store.pendingAttachments.some((a) => a.status === 'expired' || isExpired(a.expires_at)) ? '附件已过期，请移除后重新上传。' : '附件处理失败，请移除后重试。' }}</span>
      </div>

      <div class="flex items-end gap-2">
        <input
          ref="fileInputRef"
          type="file"
          class="hidden"
          multiple
          :accept="allowedExtensions.map((extension) => `.${extension}`).join(',')"
          @change="onFileChange"
        />
        <button
          type="button"
          @click="fileInputRef?.click()"
          :disabled="store.isStreaming || store.isUploadingAttachments"
          class="shrink-0 w-10 h-10 flex items-center justify-center rounded-xl border border-gray-300 text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          title="添加附件"
          data-testid="pick-attachment"
        >
          <Paperclip class="w-4 h-4" />
        </button>
      <textarea
        ref="textareaRef"
        v-model="store.inputText"
        @input="onInput"
        @keydown="onKeydown"
        rows="1"
        placeholder="描述机型和问题，例如：Mini 4 Pro 指南针怎么校准？"
        class="flex-1 resize-none border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-stone-400/50 focus:border-stone-400 max-h-[200px]"
      />
      <button
        v-if="!store.isStreaming"
        @click="send"
        :disabled="!store.canSend"
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
  </div>
</template>
