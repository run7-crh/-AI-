// frontend/src/stores/chat.ts
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type {
  Attachment,
  AttachmentStatusPayload,
  Conversation,
  Message,
  ChatMeta,
} from '@/types'
import * as convApi from '@/api/conversations'
import * as attachmentApi from '@/api/attachments'
import { streamChat } from '@/api/chat'
import { ATTACHMENT_ERROR_LABELS, isImageAttachment } from '@/utils/attachments'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const currentConversationId = ref<string | null>(null)
  const messages = ref<Message[]>([])
  const inputText = ref('')
  const isStreaming = ref(false)
  const error = ref<string | null>(null)

  // Attachments are temporary draft state. They are explicitly copied onto
  // the next user message and cleared immediately after that round starts.
  const pendingAttachments = ref<Attachment[]>([])
  const attachmentUploadProgress = ref(0)
  const isUploadingAttachments = ref(false)
  let attachmentDraftGeneration = 0

  // UI 状态（不影响核心业务逻辑）
  const sidebarCollapsed = ref(false)
  const isLoadingConversations = ref(false)
  const isLoadingMessages = ref(false)

  // 当前流式请求的 AbortController，用于手动中止
  let abortController: AbortController | null = null
  // 每个流绑定一个 assistant message，避免旧请求的迟到事件污染新请求。
  let activeRequestId: string | null = null
  let sessionGeneration = 0

  /** Drop all account-scoped state when a session ends or changes. */
  function resetSession(): void {
    sessionGeneration += 1
    stopStreaming()
    clearPendingAttachments()
    conversations.value = []
    currentConversationId.value = null
    messages.value = []
    inputText.value = ''
    error.value = null
  }

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

  function attachmentIsReady(attachment: Attachment): boolean {
    return attachment.status === 'ready' &&
      attachment.extraction_status === 'ready' &&
      (!attachment.expires_at || new Date(attachment.expires_at).getTime() > Date.now())
  }

  const allPendingAttachmentsReady = computed(() =>
    pendingAttachments.value.length > 0 && pendingAttachments.value.every(attachmentIsReady)
  )

  const hasBlockingAttachment = computed(() =>
    pendingAttachments.value.some((attachment) =>
      !attachmentIsReady(attachment)
    )
  )

  const canSend = computed(() => {
    if (isStreaming.value || isLoadingMessages.value || isUploadingAttachments.value) return false
    const hasText = inputText.value.trim().length > 0
    const hasReadyAttachments = allPendingAttachmentsReady.value
    return !hasBlockingAttachment.value && (hasText || hasReadyAttachments)
  })

  function clearPendingAttachments(): void {
    attachmentDraftGeneration += 1
    revokePreviewUrls(pendingAttachments.value)
    pendingAttachments.value = []
    attachmentUploadProgress.value = 0
    // A conversation switch or a new round invalidates the draft. The XHR
    // may finish later, but its generation token prevents stale results from
    // re-entering the new conversation.
    isUploadingAttachments.value = false
  }

  /** 释放图片预览的 blob URL（仅前端本地引用，与服务器无关）。 */
  function revokePreviewUrls(entries: Attachment[]): void {
    for (const entry of entries) {
      if (entry.preview_url) {
        try {
          URL.revokeObjectURL(entry.preview_url)
        } catch {
          // 环境不支持 object URL（如测试）则忽略
        }
        entry.preview_url = null
      }
    }
  }

  async function uploadAttachments(input: File[] | FileList): Promise<void> {
    const files = Array.from(input)
    if (!files.length || isUploadingAttachments.value) return
    if (!currentConversationId.value) await createNewConversation()
    const conversationId = currentConversationId.value
    if (!conversationId) return

    const generation = attachmentDraftGeneration
    const now = new Date().toISOString()
    const localEntries: Attachment[] = files.map((file, index) => {
      const entry: Attachment = {
        id: `local-${crypto.randomUUID()}-${index}`,
        original_name: file.name,
        extension: file.name.includes('.') ? file.name.split('.').pop()?.toLowerCase() || '' : '',
        declared_mime: file.type || null,
        size_bytes: file.size,
        status: 'uploading',
        extraction_status: 'pending',
        created_at: now,
        upload_progress: 0,
      }
      if (isImageAttachment(entry)) {
        try {
          entry.preview_url = URL.createObjectURL(file)
        } catch {
          entry.preview_url = null // 测试/受限环境无 object URL
        }
      }
      return entry
    })
    pendingAttachments.value = [...pendingAttachments.value, ...localEntries]
    isUploadingAttachments.value = true
    attachmentUploadProgress.value = 0
    try {
      const response = await attachmentApi.uploadAttachments(
        conversationId,
        files,
        (progress) => {
          attachmentUploadProgress.value = progress
          for (const entry of localEntries) entry.upload_progress = progress
        },
      )
      if (generation !== attachmentDraftGeneration) {
        // The draft was removed or the conversation changed while the XHR
        // was in flight. Clean up server-side temporary files as well.
        await Promise.allSettled(response.attachments.map((attachment) =>
          attachmentApi.deleteAttachment(conversationId, attachment.attachment_id || attachment.id)
        ))
        return
      }
      const localIds = new Set(localEntries.map((entry) => entry.id))
      const retained = pendingAttachments.value.filter((entry) => !localIds.has(entry.id))
      // 服务端按上传顺序返回；沿用本地 blob 预览（服务端不回传图片字节）。
      const serverEntries = response.attachments.map((attachment, index) => ({
        ...attachment,
        preview_url: localEntries[index]?.preview_url ?? null,
      }))
      pendingAttachments.value = [...retained, ...serverEntries]
    } catch (cause) {
      if (generation !== attachmentDraftGeneration) return
      const raw = cause instanceof Error ? cause.message : '附件上传失败'
      const message = ATTACHMENT_ERROR_LABELS[raw] || raw
      for (const entry of localEntries) {
        entry.status = 'failed'
        entry.extraction_status = 'failed'
        entry.extraction_error = message
        entry.upload_progress = 0
      }
      error.value = message
    } finally {
      if (generation === attachmentDraftGeneration) {
        isUploadingAttachments.value = false
        attachmentUploadProgress.value = 100
      }
    }
  }

  async function removeAttachment(attachmentId: string): Promise<void> {
    const attachment = pendingAttachments.value.find((item) => item.id === attachmentId)
    if (!attachment) return
    if (attachment.status === 'uploading') {
      // Invalidate the in-flight batch so a late XHR response cannot restore a
      // file the user explicitly removed.
      attachmentDraftGeneration += 1
      isUploadingAttachments.value = false
      attachmentUploadProgress.value = 0
    }
    const serverId = attachment.attachment_id || attachment.id
    if (!attachment.id.startsWith('local-') && currentConversationId.value) {
      try {
        await attachmentApi.deleteAttachment(currentConversationId.value, serverId)
      } catch (cause) {
        error.value = cause instanceof Error ? cause.message : '附件删除失败'
        return
      }
    }
    revokePreviewUrls([attachment])
    pendingAttachments.value = pendingAttachments.value.filter((item) => item.id !== attachmentId)
  }

  async function loadConversations(): Promise<void> {
    const generation = sessionGeneration
    isLoadingConversations.value = true
    try {
      const loadedConversations = await convApi.listConversations()
      if (generation !== sessionGeneration) return
      conversations.value = loadedConversations
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
    clearPendingAttachments()
    const generation = sessionGeneration
    currentConversationId.value = id
    isLoadingMessages.value = true
    try {
      const detail = await convApi.getConversation(id)
      if (generation === sessionGeneration && currentConversationId.value === id) {
        messages.value = detail.messages.map((m) => ({ ...m, isStreaming: false }))
      }
    } finally {
      isLoadingMessages.value = false
    }
  }

  async function createNewConversation(): Promise<void> {
    // 新建会话前先停止当前流，避免 isStreaming 卡住导致 UI 锁死
    stopStreaming()
    clearPendingAttachments()
    const conv = await convApi.createConversation()
    conversations.value.unshift(conv)
    currentConversationId.value = conv.id
    messages.value = []
  }

  async function deleteConversation(id: string): Promise<void> {
    await convApi.deleteConversation(id)
    conversations.value = conversations.value.filter((c) => c.id !== id)
    if (currentConversationId.value === id) {
      clearPendingAttachments()
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
    const requestId = activeRequestId
    activeRequestId = null
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    // 重置当前助手消息的流式状态
    const m = requestId ? messages.value.find((item) => item.id === requestId) : null
    if (m && m.role === 'assistant' && m.isStreaming) {
      m.isStreaming = false
      m.currentStage = ''
      finalizeRunningTrace(m, 'done')
      // 如果用户主动停止且已有内容，保留内容；无内容则标记为已停止
      if (!m.content) m.content = '_(已停止)_'
    }
    isStreaming.value = false
  }

  async function sendMessage(): Promise<void> {
    const text = inputText.value.trim()
    // Do not append to a conversation while its history is being replaced by
    // selectConversation(); otherwise the late GET response can overwrite the
    // just-created user/assistant messages.
    if (!text && !allPendingAttachmentsReady.value) {
      if (pendingAttachments.value.length > 0) error.value = '请等待附件解析完成，或删除失败附件后再发送'
      return
    }
    const readyAttachments = pendingAttachments.value.length > 0 && pendingAttachments.value.every(attachmentIsReady)
    if (!readyAttachments && pendingAttachments.value.length > 0) {
      error.value = '请等待附件解析完成，或删除失败附件后再发送'
      return
    }
    if (!canSend.value) {
      if (hasBlockingAttachment.value) error.value = '请等待附件解析完成，或删除失败附件后再发送'
      return
    }
    inputText.value = ''
    // 消息附件只保留服务端元数据；blob 预览随 clearPendingAttachments 释放。
    const attachments = pendingAttachments.value.map((item) => ({ ...item, preview_url: null }))
    clearPendingAttachments()
    await doSend(text, attachments)
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

  /** 把 trace 中所有 running 节点置为指定状态（error=后端异常，done=正常/手动停止收尾）。 */
  function finalizeRunningTrace(m: Message | null, status: 'done' | 'error'): void {
    if (!m?.trace) return
    for (const t of m.trace) {
      if (t.status === 'running') t.status = status
    }
  }

  /** 内部发送实现，供 sendMessage 与 retryLastMessage 复用。 */
  async function doSend(text: string, selectedAttachments: Attachment[] = []): Promise<void> {
    error.value = null

    if (!currentConversationId.value) {
      await createNewConversation()
    }
    const convId = currentConversationId.value as string

    const attachmentSummaries = selectedAttachments.map((attachment) => {
      const { sha256: _sha256, upload_progress: _uploadProgress, ...summary } = attachment
      return summary
    })
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
      attachments: attachmentSummaries.length ? attachmentSummaries : undefined,
    }
    messages.value.push(userMsg)

    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      isStreaming: true,
      currentStage: '',
      trace: [],
    }
    messages.value.push(assistantMsg)

    isStreaming.value = true
    const requestId = assistantMsg.id
    activeRequestId = requestId

    // 为本次请求创建 AbortController，支持手动中止
    const requestController = new AbortController()
    abortController = requestController
    let requestHadServerEvent = false
    let assistantPersisted = false
    let requestSuperseded = false
    const requestMessage = (): Message | null => {
      if (activeRequestId !== requestId) return null
      return messages.value.find((item) => item.id === requestId) ?? null
    }

    try {
      const chatRequest = {
        conversation_id: convId,
        message: text,
        ...(selectedAttachments.length
          ? { attachment_ids: selectedAttachments.map((attachment) => attachment.attachment_id || attachment.id) }
          : {}),
      }
      await streamChat(
        chatRequest,
        {
          onStage: (stage) => {
            requestHadServerEvent = true
            const m = requestMessage()
            if (!m?.isStreaming) return
            m.currentStage = stage.label  // 保留：MessageList 滚动 watch 依赖
            if (!m.trace) m.trace = []
            if (!m.traceStartedAt) m.traceStartedAt = Date.now()
            m.trace.push({ node: stage.node, label: stage.label, status: 'running' })
          },
          onReasoning: (text) => {
            const m = requestMessage()
            if (!m?.isStreaming || !m.trace) return
            // 累加到最近的 running 节点（reasoning 发生在生成节点执行期间）
            for (let i = m.trace.length - 1; i >= 0; i--) {
              if (m.trace[i].status === 'running') {
                m.trace[i].reasoning = (m.trace[i].reasoning || '') + text
                break
              }
            }
          },
          onNodeEnd: (payload) => {
            const m = requestMessage()
            if (!m?.isStreaming || !m.trace) return
            // 从后往前配对同名 running 节点（CRAG 回路多次执行各自配对）
            for (let i = m.trace.length - 1; i >= 0; i--) {
              if (m.trace[i].node === payload.node && m.trace[i].status === 'running') {
                m.trace[i].status = 'done'
                m.trace[i].durationMs = payload.duration_ms
                m.trace[i].output = payload.output
                break
              }
            }
          },
          onAttachmentStatus: (payload: AttachmentStatusPayload) => {
            requestHadServerEvent = true
            const m = requestMessage()
            if (m) m.attachment_status = payload
          },
          onToken: (token) => {
            requestHadServerEvent = true
            const m = requestMessage()
            if (m) m.content += token
          },
          onFinal: (answer) => {
            const m = requestMessage()
            if (!m?.isStreaming) return
            requestHadServerEvent = true
            assistantPersisted = true
            // 服务端在流结束时发送规范化的完整答案。直接以它为准，
            // 可消除重试过程中已经下发的重复/半截 token。
            m.content = answer
          },
          onMeta: (meta: ChatMeta) => {
            const m = requestMessage()
            if (m?.isStreaming) {
              requestHadServerEvent = true
              assistantPersisted = true
              // Compatibility for servers that only include the canonical
              // answer in meta rather than sending a dedicated final event.
              if (!m.content && meta.final_answer) m.content = meta.final_answer
              m.route_path = meta.route_path
              m.sources = meta.sources
              m.judge_log = meta.judge_log
              // P1-3: 接收质量警告（仅 quality_fail 路径有值）
              if (meta.quality_warning) m.quality_warning = meta.quality_warning
              // 第 2 阶段：绑定 query_log_id，供反馈接口使用
              if (meta.query_log_id) m.query_log_id = meta.query_log_id
              // 阶段 2：安全与人工升级状态（旧服务缺字段时保持 undefined）
              if (meta.safety_flag !== undefined) m.safety_flag = meta.safety_flag
              if (meta.safety_level !== undefined) m.safety_level = meta.safety_level
              if (meta.safety_situation !== undefined) m.safety_situation = meta.safety_situation
              if (meta.escalation_required !== undefined) {
                m.escalation_required = meta.escalation_required
              }
              // 阶段 3/5 字段：旧后端没有时保持 undefined，避免改动旧消息。
              if (meta.intent !== undefined) m.intent = meta.intent
              if (meta.metadata_constraints !== undefined) m.metadata_constraints = meta.metadata_constraints
              if (meta.document_type_priority !== undefined) m.document_type_priority = meta.document_type_priority
              if (meta.recommended_action !== undefined) m.recommended_action = meta.recommended_action
              if (meta.agent_ticket !== undefined) m.agent_ticket = meta.agent_ticket
              if (meta.attachment_ids?.length) {
                m.attachment_status = {
                  phase: 'context',
                  status: meta.attachment_parse_status === 'failed' ? 'failed' : 'ready',
                  attachment_ids: meta.attachment_ids,
                  message: meta.attachment_parse_status === 'failed'
                    ? '附件上下文处理失败'
                    : '附件仅作为本轮临时上下文使用',
                }
              }
            }
          },
          onError: (msg) => {
            requestHadServerEvent = true
            const m = requestMessage()
            if (!m) return
            error.value = msg
            m.isStreaming = false
            finalizeRunningTrace(m, 'error')
            if (!m.content) m.content = `**错误**：${msg}`
          },
          onDone: () => {
            const m = requestMessage()
            if (m) {
              m.isStreaming = false
              m.currentStage = ''
              finalizeRunningTrace(m, 'done')
              if (m.traceStartedAt !== undefined) {
                m.traceDurationMs = Date.now() - m.traceStartedAt
              }
            }
            if (activeRequestId === requestId) isStreaming.value = false
          },
        },
        requestController.signal
      )
    } catch (e) {
      // AbortError 是用户主动中止，不算错误
      if (e instanceof Error && e.name === 'AbortError') {
        const m = requestMessage()
        if (m && m.role === 'assistant' && m.isStreaming) {
          m.isStreaming = false
          m.currentStage = ''
          finalizeRunningTrace(m, 'done')
          if (!m.content) m.content = '_(已停止)_'
        }
        if (activeRequestId === requestId) isStreaming.value = false
        return
      }
      if (activeRequestId !== requestId) return
      const msg = e instanceof Error ? e.message : String(e)
      error.value = msg
      const m = requestMessage()
      if (m && m.role === 'assistant') {
        m.isStreaming = false
        if (!m.content) m.content = `**错误**：${msg}`
      }
      if (activeRequestId === requestId) isStreaming.value = false
    } finally {
      if (activeRequestId === requestId) {
        activeRequestId = null
        abortController = null
      } else {
        requestSuperseded = true
      }
    }

    // SSE error/EOF paths persist at most the user message.  Only count the
    // assistant when final/meta proves the backend inserted it; a transport
    // failure before any event should not change the local count at all.
    const idx = conversations.value.findIndex((c) => c.id === convId)
    const persistedDelta = assistantPersisted ? 2 : requestHadServerEvent ? 1 : 0
    if (!requestSuperseded && idx !== -1 && persistedDelta > 0) {
      const conv = conversations.value[idx]
      conv.message_count += persistedDelta
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
    pendingAttachments,
    attachmentUploadProgress,
    isUploadingAttachments,
    canSend,
    uploadAttachments,
    removeAttachment,
    clearPendingAttachments,
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
    resetSession,
  }
})
