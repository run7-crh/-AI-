<!-- frontend/src/components/TicketDraftCard.vue -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Ticket } from '@/types'
import { useTicketsStore } from '@/stores/tickets'
import { Loader2, Ticket as TicketIcon } from 'lucide-vue-next'

const props = defineProps<{ conversationId: string }>()
const emit = defineEmits<{ created: [ticket: Ticket]; submitted: [ticket: Ticket] }>()

const store = useTicketsStore()
const draft = ref<Ticket | null>(null)
const draftError = ref<string | null>(null)

const canSubmit = computed(() => draft.value?.status === 'draft')

async function createDraft(): Promise<void> {
  draftError.value = null
  try {
    draft.value = await store.createDraft(props.conversationId)
    emit('created', draft.value)
  } catch {
    draftError.value = store.error || '创建工单草稿失败，请稍后重试'
  }
}

async function submitDraft(): Promise<void> {
  if (!draft.value) return
  draftError.value = null
  try {
    draft.value = await store.submit(draft.value.id)
    emit('submitted', draft.value)
  } catch {
    draftError.value = store.error || '提交工单失败，请稍后重试'
  }
}
</script>

<template>
  <div
    class="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-xs"
    data-testid="ticket-draft-card"
  >
    <div v-if="!draft" class="flex items-center justify-between gap-2">
      <span class="text-stone-700">排查未解决？可以把本次会话整理为售后工单，由客服跟进。</span>
      <button
        class="flex shrink-0 items-center gap-1 rounded-lg border border-stone-300 bg-white px-2.5 py-1 font-medium text-stone-700 transition-colors hover:border-stone-400 hover:bg-stone-100 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="store.acting"
        data-testid="create-draft-button"
        @click="createDraft"
      >
        <Loader2 v-if="store.acting" class="h-3.5 w-3.5 animate-spin" />
        <TicketIcon v-else class="h-3.5 w-3.5" />
        生成工单草稿
      </button>
    </div>

    <div v-else class="space-y-2">
      <div class="flex flex-wrap items-center gap-2">
        <span class="font-semibold text-stone-800" data-testid="draft-number">{{ draft.ticket_number }}</span>
        <span class="rounded-full border border-stone-200 bg-white px-2 py-0.5 text-gray-500">
          {{ draft.status === 'draft' ? '草稿' : '已提交' }}
        </span>
      </div>
      <p class="text-stone-600">{{ draft.title }}</p>
      <p class="whitespace-pre-wrap text-gray-500">{{ draft.problem_summary }}</p>
      <button
        v-if="canSubmit"
        class="flex items-center gap-1 rounded-lg bg-stone-800 px-2.5 py-1 font-medium text-white transition-colors hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="store.acting"
        data-testid="submit-draft-button"
        @click="submitDraft"
      >
        <Loader2 v-if="store.acting" class="h-3.5 w-3.5 animate-spin" />
        确认提交工单
      </button>
      <div v-else class="font-medium text-emerald-700" data-testid="draft-submitted">
        工单已提交，客服会尽快跟进处理。
      </div>
    </div>

    <div v-if="draftError" class="mt-2 text-red-600" data-testid="draft-error">{{ draftError }}</div>
  </div>
</template>
