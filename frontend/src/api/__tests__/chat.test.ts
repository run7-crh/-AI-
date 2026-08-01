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
      'data: {"type":"stage","data":"正在检索..."}',
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
      { type: 'stage', data: '正在检索...' },
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
      'data: {"type":"stage","data":"正在检索..."}',
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
      { type: 'stage', data: '正在检索...' },
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
})
