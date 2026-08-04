// frontend/src/stores/chat.ts
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { Conversation, Message, ChatMeta } from '@/types'
import * as convApi from '@/api/conversations'
import { streamChat } from '@/api/chat'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const inputText = ref('')
  const isStreaming = ref(false)
  const error = ref<string | null>(null)

  // UI 状态（不影响核心业务逻辑）
  const sidebarCollapsed = ref(false)
  const isLoadingConversations = ref(false)
  const isLoadingMessages = ref(false)

  // 当前流式请求的 AbortController，用于手动中止
  let abortController: AbortController | null = null

  // 从 localStorage 恢复侧边栏折叠状态
  try {
    const saved = localStorage.getItem('sidebarCollapsed')
    if (saved !== null) sidebarCollapsed.value = saved === 'true'
  } catch {
    // 忽略隐私模式/localStorage 不可用
  }
  watch(sidebarCollapsed, (v) => {
    try {
      localStorage.setItem('sidebarCollapsed', String(v))
    } catch {
      /* ignore */
    }
  })

  const currentConversation = computed<Conversation | null>(() =>
    conversations.value.find((c) => c.id === currentConversationId.value) ?? null
  )

  const lastAssistantMessage = computed<Message | null>(() => {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'assistant') return messages.value[i]
    }
    return null
  })

  async function loadConversations(): Promise<void> {
    isLoadingConversations.value = true
    try {
      conversations.value = await convApi.listConversations()
      if (conversations.value.length > 0 && !currentConversationId.value) {
        await selectConversation(conversations.value[0].id)
      }
    } finally {
      isLoadingConversations.value = false
    }
  }

  async function selectConversation(id: string): Promise<void> {
    // 切换会话前先停止当前流（避免旧流事件污染新会话）
    stopStreaming()
    currentConversationId.value = id
    isLoadingMessages.value = true
    try {
      const detail = await convApi.getConversation(id)
      messages.value = detail.messages.map((m) => ({ ...m, isStreaming: false }))
    } finally {
      isLoadingMessages.value = false
    }
  }

  async function createNewConversation(): Promise<void> {
    // 新建会话前先停止当前流，避免 isStreaming 卡住导致 UI 锁死
    stopStreaming()
    const conv = await convApi.createConversation()
    conversations.value.unshift(conv)
    currentConversationId.value = conv.id
    messages.value = []
  }

  async function deleteConversation(id: string): Promise<void> {
    await convApi.deleteConversation(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversationId.value === id) {
      currentConversationId.value = null
      messages.value = []
      if (conversations.value.length > 0) {
        await selectConversation(conversations.value[0].id)
      }
    }
  }

  async function updateTitle(id: string, title: string): Promise<void> {
    const updated = await convApi.updateConversation(id, title)
    const idx = conversations.value.findIndex((c) => c.id === id)
    if (idx !== -1) conversations.value[idx] = { ...conversations.value[idx], ...updated }
  }

  /** 手动停止当前流式请求。
   * 区分两种情况：
   * - 用户主动停止（如新建会话/点停止按钮）：不显示错误，保留已生成内容
   * - 网络超时/错误：显示错误信息
   */
  function stopStreaming(): void {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    // 重置当前助手消息的流式状态
    const m = messages.value[messages.value.length - 1]
    if (m && m.role === 'assistant' && m.isStreaming) {
      m.isStreaming = false
      m.currentStage = ''
      // 如果用户主动停止且已有内容，保留内容；无内容则标记为已停止
      if (!m.content) m.content = '_(已停止)_'
    }
    isStreaming.value = false
  }

  async function sendMessage(): Promise<void> {
    const text = inputText.value.trim()
    if (!text || isStreaming.value) return
    inputText.value = ''
    await doSend(text)
  }

  /** 重试最后一条用户消息：将该问题重新填入输入框并重新发送。 */
  async function retryLastMessage(): Promise<void> {
    let userIdx = -1
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        userIdx = i
        break
      }
    }
    if (userIdx === -1) return
    inputText.value = messages.value[userIdx].content
    messages.value = messages.value.slice(0, userIdx)
    error.value = null
    await sendMessage()
  }

  /** 重新生成指定助手回复：回退到其前一条用户消息并重新发送。 */
  async function regenerateResponse(assistantMessageId: string): Promise<void> {
    const assistantIdx = messages.value.findIndex((m) => m.id === assistantMessageId)
    if (assistantIdx === -1) return
    let userIdx = -1
    for (let i = assistantIdx - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        userIdx = i
        break
      }
    }
    if (userIdx === -1) return
    inputText.value = messages.value[userIdx].content
    messages.value = messages.value.slice(0, userIdx)
    error.value = null
    await sendMessage()
  }

  /** 编辑用户消息：将内容填入输入框并删除该消息及其之后的消息。 */
  function editUserMessage(messageId: string): void {
    const idx = messages.value.findIndex((m) => m.id === messageId)
    if (idx === -1) return
    inputText.value = messages.value[idx].content
    messages.value = messages.value.slice(0, idx)
    error.value = null
  }

  /** 内部发送实现，供 sendMessage 与 retryLastMessage 复用。 */
  async function doSend(text: string): Promise<void> {
    error.value = null

    if (!currentConversationId.value) {
      await createNewConversation()
    }
    const convId = currentConversationId.value as string

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    }
    messages.value.push(userMsg)

    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      isStreaming: true,
      currentStage: '',
    }
    messages.value.push(assistantMsg)

    isStreaming.value = true

    // 为本次请求创建 AbortController，支持手动中止
    abortController = new AbortController()

    try {
      await streamChat(
        { conversation_id: convId, message: text },
        {
          onStage: (stage) => {
            const m = messages.value[messages.value.length - 1]
            if (m && m.role === 'assistant') m.currentStage = stage
          },
          onToken: (token) => {
            const m = messages.value[messages.value.length - 1]
            if (m && m.role === 'assistant') m.content += token
          },
          onMeta: (meta: ChatMeta) => {
            const m = messages.value[messages.value.length - 1]
            if (m && m.role === 'assistant') {
              m.route_path = meta.route_path
              m.sources = meta.sources
              m.judge_log = meta.judge_log
              // P1-3: 接收质量警告（仅 quality_fail 路径有值）
              if (meta.quality_warning) m.quality_warning = meta.quality_warning
              // 第 2 阶段：绑定 query_log_id，供反馈接口使用
              if (meta.query_log_id) m.query_log_id = meta.query_log_id
            }
          },
          onError: (msg) => {
            error.value = msg
            const m = messages.value[messages.value.length - 1]
            if (m && m.role === 'assistant') {
              m.isStreaming = false
              if (!m.content) m.content = `**错误**：${msg}`
            }
          },
          onDone: () => {
            const m = messages.value[messages.value.length - 1]
            if (m && m.role === 'assistant') {
              m.isStreaming = false
              m.currentStage = ''
            }
            isStreaming.value = false
          },
        },
        abortController.signal
      )
    } catch (e) {
      // AbortError 是用户主动中止，不算错误
      if (e instanceof Error && e.name === 'AbortError') {
        const m = messages.value[messages.value.length - 1]
        if (m && m.role === 'assistant' && m.isStreaming) {
          m.isStreaming = false
          m.currentStage = ''
          if (!m.content) m.content = '_(已停止)_'
        }
        isStreaming.value = false
        return
      }
      const msg = e instanceof Error ? e.message : String(e)
      error.value = msg
      const m = messages.value[messages.value.length - 1]
      if (m && m.role === 'assistant') {
        m.isStreaming = false
        if (!m.content) m.content = `**错误**：${msg}`
      }
      isStreaming.value = false
    } finally {
      abortController = null
    }

    // 乐观更新会话列表
    const idx = conversations.value.findIndex((c) => c.id === convId)
    if (idx !== -1) {
      const conv = conversations.value[idx]
      conv.message_count += 2
      conv.updated_at = new Date().toISOString()
      conversations.value.splice(idx, 1)
      conversations.value.unshift(conv)
    }
  }

  function clearError(): void {
    error.value = null
  }

  return {
    conversations,
    currentConversationId,
    currentConversation,
    lastAssistantMessage,
    messages,
    inputText,
    isStreaming,
    error,
    sidebarCollapsed,
    isLoadingConversations,
    isLoadingMessages,
    loadConversations,
    selectConversation,
    createNewConversation,
    deleteConversation,
    updateTitle,
    sendMessage,
    retryLastMessage,
    regenerateResponse,
    editUserMessage,
    stopStreaming,
    clearError,
  }
})
