// frontend/src/api/chat.ts
// SSE 流式客户端：解析 sse-starlette 推送的事件，分发到回调。
// 事件格式：data: {"type":"stage|token|final|meta|error|done","data":...}\n\n
import type { ChatRequest, StreamCallbacks, ChatMeta, StagePayload, NodeEndPayload, AttachmentStatusPayload } from '@/types'
import { apiFetch } from './http'

// 无数据超时：连续 60s 收不到任何 chunk 视为连接卡死，主动中止。
// DeepSeek 偶发 StreamChunkTimeoutError（120s），这里更激进些提前止损。
const NO_DATA_TIMEOUT_MS = 60_000

export async function streamChat(
  req: ChatRequest,
  cb: StreamCallbacks,
  signal?: AbortSignal
): Promise<void> {
  const r = await apiFetch('/api/chat', {
    method: 'POST',
    // 显式声明 Accept: text/event-stream，避免某些 proxy/浏览器缓冲整个响应
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
    },
    body: JSON.stringify(req),
    signal,
  })
  if (!r.ok) {
    throw new Error(`HTTP ${r.status}`)
  }
  if (!r.body) {
    throw new Error('Response has no body')
  }

  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let doneNotified = false
  let streamCompleted = false
  let timedOut = false
  let sawDone = false
  let sawTerminalPayload = false

  // 服务端通常会发送 done，但代理/连接提前关闭时可能没有该事件。
  // 统一去重，避免显式 done + EOF 触发两次 onDone。
  const notifyDone = (): void => {
    if (doneNotified) return
    doneNotified = true
    cb.onDone()
  }
  const callbacks: StreamCallbacks = { ...cb, onDone: notifyDone }

  // 无数据超时定时器：每次收到 chunk 重置；超时则 abort
  let timeoutId: ReturnType<typeof setTimeout> | null = null
  const resetTimer = (): void => {
    if (timeoutId) clearTimeout(timeoutId)
    timeoutId = setTimeout(() => {
      timedOut = true
      // 超时主动取消 reader，触发下方的 AbortError
      try { reader.cancel().catch(() => {}) } catch { /* ignore */ }
    }, NO_DATA_TIMEOUT_MS)
  }
  const clearTimer = (): void => {
    if (timeoutId) {
      clearTimeout(timeoutId)
      timeoutId = null
    }
  }

  resetTimer()
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        streamCompleted = true
        break
      }
      // 收到数据，重置超时
      resetTimer()
      // Normalize CRLF after appending to the buffer: a proxy may split the
      // CR and LF of one pair across two chunks.  Normalizing each incoming
      // chunk separately would miss that boundary and lose whole events.
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n')

      // SSE events are separated by an empty line.
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        const data = parseSSEData(rawEvent)
        if (data) {
          const eventType = dispatchEvent(data, callbacks)
          if (eventType === 'done') sawDone = true
          if (eventType === 'final' || eventType === 'meta' || eventType === 'error') {
            sawTerminalPayload = true
          }
        }
      }
    }
    // Flush a possible final UTF-8 code point held by TextDecoder.
    buffer += decoder.decode()
    // flush 残留（无尾随双换行的情况）
    if (buffer.trim()) {
      const data = parseSSEData(buffer)
      if (data) {
        const eventType = dispatchEvent(data, callbacks)
        if (eventType === 'done') sawDone = true
        if (eventType === 'final' || eventType === 'meta' || eventType === 'error') {
          sawTerminalPayload = true
        }
      }
    }
    if (streamCompleted && !doneNotified) {
      // AbortController cancellation is handled by the store so it can mark
      // an interrupted answer as stopped.  Do not turn that cancellation into
      // a normal completion merely because reader.cancel() resolved with done.
      if (signal?.aborted) {
        throw new DOMException('The stream was aborted', 'AbortError')
      }
      if (timedOut) cb.onError('流式响应超时，请稍后重试')
      if (!sawDone && !sawTerminalPayload && !timedOut) {
        cb.onError('流式响应意外中断，请重试')
      }
      notifyDone()
    }
  } finally {
    clearTimer()
    reader.releaseLock()
  }
}

/** 从一个 SSE 事件块（可能含多行 field: value）提取 data 字段拼接结果。 */
function parseSSEData(raw: string): string | null {
  const lines = raw.split(/\r\n|\n|\r/)
  let data = ''
  for (const line of lines) {
    if (line.startsWith('data:')) {
      data += line.slice(5).trim()
    }
    // 忽略 event: / id: / retry: / 注释行
  }
  return data || null
}

function dispatchEvent(rawData: string, cb: StreamCallbacks): string | null {
  let parsed: { type: string; data?: unknown }
  try {
    parsed = JSON.parse(rawData)
  } catch {
    return null // 非 JSON（心跳或注释），忽略
  }
  switch (parsed.type) {
    case 'stage':
      cb.onStage(parsed.data as StagePayload)
      break
    case 'token':
      cb.onToken(parsed.data as string)
      break
    case 'final':
      if (typeof parsed.data === 'string') cb.onFinal?.(parsed.data)
      break
    case 'reasoning':
      cb.onReasoning?.(parsed.data as string)
      break
    case 'node_end':
      cb.onNodeEnd?.(parsed.data as NodeEndPayload)
      break
    case 'attachment':
    case 'attachment_status':
      cb.onAttachmentStatus?.(parsed.data as AttachmentStatusPayload)
      break
    case 'meta':
      cb.onMeta(parsed.data as ChatMeta)
      break
    case 'error':
      cb.onError(
        (parsed.data && typeof parsed.data === 'object' && 'message' in parsed.data
          ? String((parsed.data as { message: unknown }).message)
          : '未知错误')
      )
      break
    case 'done':
      cb.onDone()
      break
  }
  return parsed.type
}
