// frontend/src/api/__tests__/chat.test.ts
import { describe, it, expect, vi } from 'vitest'
import { streamChat } from '../chat'

function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
}

describe('streamChat SSE parsing', () => {
  it('parses stage / token / done events', async () => {
    const sseData = [
      'data: {"type":"stage","data":{"node":"rag_retrieve","label":"正在检索知识库..."}}',
      '',
      'data: {"type":"token","data":"你好"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    const events: Array<{ type: string; data?: unknown }> = []
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: (s) => events.push({ type: 'stage', data: s }),
        onToken: (t) => events.push({ type: 'token', data: t }),
        onMeta: (m) => events.push({ type: 'meta', data: m }),
        onError: (e) => events.push({ type: 'error', data: e }),
        onDone: () => events.push({ type: 'done' }),
      }
    )

    expect(events).toEqual([
      { type: 'stage', data: { node: 'rag_retrieve', label: '正在检索知识库...' } },
      { type: 'token', data: '你好' },
      { type: 'done' },
    ])
  })

  it('handles events split across chunks', async () => {
    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([
        'data: {"type":"token","data":"你',
        '好"}\n\n',
        'data: {"type":"done"}\n\n',
      ]),
    })

    const tokens: string[] = []
    let doneCount = 0
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: (t) => tokens.push(t),
        onMeta: () => {},
        onError: () => {},
        onDone: () => doneCount++,
      }
    )

    expect(tokens).toEqual(['你好'])
    expect(doneCount).toBe(1)
  })

  it('dispatches meta event', async () => {
    const sseData = [
      'data: {"type":"meta","data":{"route_path":"local","sources":[],"judge_log":[]}}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    let metaResult: unknown = null
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onMeta: (m) => { metaResult = m },
        onError: () => {},
        onDone: () => {},
      }
    )

    expect(metaResult).toEqual({ route_path: 'local', sources: [], judge_log: [] })
  })

  it('dispatches error event with message', async () => {
    const sseData = [
      'data: {"type":"error","data":{"message":"LLM 调用失败"}}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    let errMsg: string | null = null
    let doneCount = 0
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onMeta: () => {},
        onError: (e) => { errMsg = e },
        onDone: () => doneCount++,
      }
    )

    expect(errMsg).toBe('LLM 调用失败')
    expect(doneCount).toBe(1)
  })

  it('throws on HTTP error', async () => {
    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: false, status: 500 })
    await expect(streamChat(
      { conversation_id: '1', message: 'x' },
      { onStage: () => {}, onToken: () => {}, onMeta: () => {}, onError: () => {}, onDone: () => {} }
    )).rejects.toThrow('HTTP 500')
  })

  it('ignores non-JSON data lines (heartbeat/comment)', async () => {
    const sseData = [
      ': this is a comment',
      '',
      'data: {"type":"token","data":"ok"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    const tokens: string[] = []
    let doneCount = 0
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: (t) => tokens.push(t),
        onMeta: () => {},
        onError: () => {},
        onDone: () => doneCount++,
      }
    )

    expect(tokens).toEqual(['ok'])
    expect(doneCount).toBe(1)
  })

  it('parses CRLF line endings (sse-starlette format)', async () => {
    // sse-starlette 用 \r\n 作为行尾，事件分隔符是 \r\n\r\n。
    // 若前端用 indexOf('\n\n') 会被 \r 阻断，所有事件堆在 buffer 里。
    const sseData = [
      'event: message',
      'data: {"type":"stage","data":{"node":"rag_retrieve","label":"正在检索知识库..."}}',
      '',
      'event: message',
      'data: {"type":"token","data":"你好"}',
      '',
      'event: message',
      'data: {"type":"done"}',
      '',
    ].join('\r\n') + '\r\n'

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    const events: Array<{ type: string; data?: unknown }> = []
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: (s) => events.push({ type: 'stage', data: s }),
        onToken: (t) => events.push({ type: 'token', data: t }),
        onMeta: () => {},
        onError: () => {},
        onDone: () => events.push({ type: 'done' }),
      }
    )

    expect(events).toEqual([
      { type: 'stage', data: { node: 'rag_retrieve', label: '正在检索知识库...' } },
      { type: 'token', data: '你好' },
      { type: 'done' },
    ])
  })

  it('parses CRLF events split across chunks', async () => {
    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([
        'event: message\r\ndata: {"type":"token","data":"你',
        '好"}\r\n\r\nevent: message\r\ndata: {"type":"done"}\r\n\r\n',
      ]),
    })

    const tokens: string[] = []
    let doneCount = 0
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: (t) => tokens.push(t),
        onMeta: () => {},
        onError: () => {},
        onDone: () => doneCount++,
      }
    )

    expect(tokens).toEqual(['你好'])
    expect(doneCount).toBe(1)
  })

  it('parses a CRLF event boundary split between chunks', async () => {
    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([
        'data: {"type":"token","data":"先"}\r\n\r',
        '\ndata: {"type":"done"}\r\n\r\n',
      ]),
    })

    const tokens: string[] = []
    let doneCount = 0
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: (token) => tokens.push(token),
        onMeta: () => {},
        onError: () => {},
        onDone: () => doneCount++,
      }
    )

    expect(tokens).toEqual(['先'])
    expect(doneCount).toBe(1)
  })

  it('dispatches node_end and reasoning events', async () => {
    const sseData = [
      'data: {"type":"node_end","data":{"node":"rewrite_query","label":"正在理解问题...","duration_ms":120,"output":{"rewritten_query":"什么是 RAG"}}}',
      '',
      'data: {"type":"reasoning","data":"用户在问 RAG"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    const nodeEnds: unknown[] = []
    const reasonings: string[] = []
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onNodeEnd: (p) => nodeEnds.push(p),
        onReasoning: (t) => reasonings.push(t),
        onMeta: () => {},
        onError: () => {},
        onDone: () => {},
      }
    )

    expect(nodeEnds).toEqual([
      {
        node: 'rewrite_query',
        label: '正在理解问题...',
        duration_ms: 120,
        output: { rewritten_query: '什么是 RAG' },
      },
    ])
    expect(reasonings).toEqual(['用户在问 RAG'])
  })

  it('dispatches optional attachment status events without affecting legacy callbacks', async () => {
    const sseData = [
      'data: {"type":"attachment","data":{"phase":"parse","status":"ready","attachment_ids":["att_1"],"count":1}}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')
    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    const statuses: unknown[] = []
    await streamChat(
      { conversation_id: '1', message: '', attachment_ids: ['att_1'] },
      {
        onStage: () => {}, onToken: () => {}, onMeta: () => {}, onError: () => {}, onDone: () => {},
        onAttachmentStatus: (payload) => statuses.push(payload),
      },
    )
    expect(statuses).toEqual([{ phase: 'parse', status: 'ready', attachment_ids: ['att_1'], count: 1 }])
  })

  it('tolerates missing optional onNodeEnd/onReasoning callbacks', async () => {
    const sseData = [
      'data: {"type":"node_end","data":{"node":"x","label":"y","duration_ms":1,"output":{}}}',
      '',
      'data: {"type":"reasoning","data":"z"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    let done = false
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onMeta: () => {},
        onError: () => {},
        onDone: () => { done = true },
      }
    )
    expect(done).toBe(true) // 可选回调缺失时不抛错
  })

  it('reports an interrupted stream when EOF has no terminal payload', async () => {
    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({
      ok: true,
      // A proxy or an interrupted server may close a valid response without
      // delivering the final SSE event.
      body: makeStream(['data: {"type":"token","data":"最后一段"}\n\n']),
    })

    let doneCount = 0
    let errorMessage: string | null = null
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onMeta: () => {},
        onError: (message) => { errorMessage = message },
        onDone: () => { doneCount++ },
      }
    )

    expect(doneCount).toBe(1)
    expect(errorMessage).toBe('流式响应意外中断，请重试')
  })

  it('accepts EOF after a canonical final event without done', async () => {
    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({
      ok: true,
      body: makeStream([
        'data: {"type":"final","data":"完整答案"}\n\n',
      ]),
    })

    let finalAnswer: string | null = null
    let errorMessage: string | null = null
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onFinal: (answer) => { finalAnswer = answer },
        onMeta: () => {},
        onError: (message) => { errorMessage = message },
        onDone: () => {},
      }
    )

    expect(finalAnswer).toBe('完整答案')
    expect(errorMessage).toBeNull()
  })

  it('dispatches a final event so the client can reconcile streamed text', async () => {
    const sseData = [
      'data: {"type":"token","data":"重复"}',
      '',
      'data: {"type":"final","data":"最终答案"}',
      '',
      'data: {"type":"done"}',
      '',
    ].join('\n')

    ;(globalThis.fetch as any) = vi.fn().mockResolvedValue({ ok: true, body: makeStream([sseData]) })

    let finalAnswer: string | null = null
    await streamChat(
      { conversation_id: '1', message: 'x' },
      {
        onStage: () => {},
        onToken: () => {},
        onFinal: (answer) => { finalAnswer = answer },
        onMeta: () => {},
        onError: () => {},
        onDone: () => {},
      }
    )

    expect(finalAnswer).toBe('最终答案')
  })
})
