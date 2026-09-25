// frontend/src/stores/__tests__/chat.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '../chat'
import * as convApi from '@/api/conversations'
import * as chatApi from '@/api/chat'

vi.mock('@/api/conversations')
vi.mock('@/api/chat')

describe('chat store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadConversations loads and selects first', async () => {
    ;(convApi.listConversations as any).mockResolvedValue([
      { id: '1', title: 'A', message_count: 0, created_at: '', updated_at: '' },
    ])
    ;(convApi.getConversation as any).mockResolvedValue({ id: '1', messages: [] })

    const store = useChatStore()
    await store.loadConversations()
    expect(store.conversations.length).toBe(1)
    expect(store.currentConversationId).toBe('1')
  })

  it('loadConversations does not select when empty', async () => {
    ;(convApi.listConversations as any).mockResolvedValue([])

    const store = useChatStore()
    await store.loadConversations()
    expect(store.conversations.length).toBe(0)
    expect(store.currentConversationId).toBeNull()
  })

  it('sendMessage creates conversation if none selected', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onStage({ node: 'rewrite_query', label: '正在理解问题...' })
      cb.onToken('回')
      cb.onToken('答')
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = '测试'
    await store.sendMessage()

    expect(store.messages.length).toBe(2) // user + assistant
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[0].content).toBe('测试')
    expect(store.messages[1].role).toBe('assistant')
    expect(store.messages[1].content).toBe('回答')
    expect(store.messages[1].currentStage).toBe('') // done 后清空
    expect(store.isStreaming).toBe(false)
    expect(store.currentConversationId).toBe('new')
  })

  it('sendMessage ignores empty input', async () => {
    const store = useChatStore()
    store.inputText = '   '
    await store.sendMessage()
    expect(store.messages.length).toBe(0)
    expect(chatApi.streamChat).not.toHaveBeenCalled()
  })

  it('sendMessage blocks when already streaming', async () => {
    const store = useChatStore()
    store.inputText = '第一条'
    store.isStreaming = true
    await store.sendMessage()
    expect(store.messages.length).toBe(0)
    expect(chatApi.streamChat).not.toHaveBeenCalled()
  })

  it('sendMessage captures meta into assistant message', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onToken('答案')
      cb.onMeta({ route_path: 'local', sources: [{ content: 'c', source: 'a.md', title: 'A', score: 0.9 }], judge_log: [], safety_flag: true, safety_level: 'high', safety_situation: 'charging', escalation_required: true, intent: 'troubleshooting' })
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    expect(store.messages[1].route_path).toBe('local')
    expect(store.messages[1].sources?.length).toBe(1)
    expect(store.messages[1].sources?.[0].source).toBe('a.md')
    expect(store.messages[1].safety_level).toBe('high')
    expect(store.messages[1].escalation_required).toBe(true)
    expect(store.messages[1].intent).toBe('troubleshooting')
  })

  it('reconciles streamed tokens with the final answer event', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onToken('重复片段')
      cb.onFinal('最终答案')
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    expect(store.messages[1].content).toBe('最终答案')
    expect(store.messages[1].isStreaming).toBe(false)
  })

  it('sendMessage captures error event', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onError('LLM 调用失败')
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    expect(store.error).toBe('LLM 调用失败')
    expect(store.messages[1].isStreaming).toBe(false)
    expect(store.messages[1].content).toContain('LLM 调用失败')
  })

  it('selectConversation loads messages', async () => {
    ;(convApi.getConversation as any).mockResolvedValue({
      id: 'c1', messages: [
        { id: 'm1', role: 'user', content: 'hi', created_at: '' },
        { id: 'm2', role: 'assistant', content: 'hello', created_at: '' },
      ],
    })

    const store = useChatStore()
    await store.selectConversation('c1')

    expect(store.currentConversationId).toBe('c1')
    expect(store.messages.length).toBe(2)
    expect(store.messages[1].content).toBe('hello')
  })

  it('selectConversation preserves persisted safety and intent metadata', async () => {
    ;(convApi.getConversation as any).mockResolvedValue({
      id: 'c1', messages: [{
        id: 'm2', role: 'assistant', content: '请先降落', created_at: '',
        safety_flag: true, safety_level: 'high', safety_situation: 'in_flight',
        escalation_required: true, intent: 'flight_safety',
        metadata_constraints: { product_model: 'mini_4_pro' },
        document_type_priority: ['safety'],
      }],
    })

    const store = useChatStore()
    await store.selectConversation('c1')

    expect(store.messages[0].safety_flag).toBe(true)
    expect(store.messages[0].escalation_required).toBe(true)
    expect(store.messages[0].intent).toBe('flight_safety')
    expect(store.messages[0].metadata_constraints).toEqual({ product_model: 'mini_4_pro' })
    expect(store.messages[0].document_type_priority).toEqual(['safety'])
  })

  it('deleteConversation removes and selects next', async () => {
    ;(convApi.deleteConversation as any).mockResolvedValue(undefined)
    ;(convApi.getConversation as any).mockResolvedValue({ id: '2', messages: [] })

    const store = useChatStore()
    store.conversations = [
      { id: '1', title: 'A', message_count: 0, created_at: '', updated_at: '' },
      { id: '2', title: 'B', message_count: 0, created_at: '', updated_at: '' },
    ]
    store.currentConversationId = '1'
    store.messages = [{ id: 'm', role: 'user', content: 'x', created_at: '' }]

    await store.deleteConversation('1')

    expect(store.conversations.length).toBe(1)
    expect(store.conversations[0].id).toBe('2')
    expect(store.currentConversationId).toBe('2')
  })

  it('sendMessage maintains trace state machine with CRAG loop', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onStage({ node: 'rewrite_query', label: '正在理解问题...' })
      cb.onNodeEnd({ node: 'rewrite_query', label: '正在理解问题...', duration_ms: 120, output: { rewritten_query: '什么是 RAG' } })
      cb.onStage({ node: 'rag_retrieve', label: '正在检索知识库...' })
      cb.onNodeEnd({ node: 'rag_retrieve', label: '正在检索知识库...', duration_ms: 300, output: { avg_reranker_score: 0.2 } })
      // CRAG 回路：同名节点第二次执行，追加第二个节点行
      cb.onStage({ node: 'rag_retrieve', label: '正在检索知识库...' })
      cb.onNodeEnd({ node: 'rag_retrieve', label: '正在检索知识库...', duration_ms: 350, output: { avg_reranker_score: 0.8 } })
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    const trace = store.messages[1].trace!
    expect(trace.length).toBe(3)
    expect(trace[0]).toMatchObject({
      node: 'rewrite_query', status: 'done', durationMs: 120,
      output: { rewritten_query: '什么是 RAG' },
    })
    expect(trace[1]).toMatchObject({ node: 'rag_retrieve', status: 'done', durationMs: 300 })
    expect(trace[2]).toMatchObject({ node: 'rag_retrieve', status: 'done', durationMs: 350 })
    // 挂钟总时长已记录
    expect(typeof store.messages[1].traceDurationMs).toBe('number')
  })

  it('reasoning accumulates on the current running node', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onStage({ node: 'multi_step_reason', label: '正在逐步推理...' })
      cb.onReasoning?.('第一步，')
      cb.onReasoning?.('分析问题。')
      cb.onNodeEnd({ node: 'multi_step_reason', label: '正在逐步推理...', duration_ms: 900, output: {} })
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    const trace = store.messages[1].trace!
    expect(trace[0].reasoning).toBe('第一步，分析问题。')
    expect(trace[0].status).toBe('done')
  })

  it('error event marks running trace node as error', async () => {
    ;(convApi.createConversation as any).mockResolvedValue({
      id: 'new', title: '', message_count: 0, created_at: '', updated_at: '',
    })
    ;(convApi.getConversation as any).mockResolvedValue({ id: 'new', messages: [] })
    ;(chatApi.streamChat as any).mockImplementation(async (_req: unknown, cb: any) => {
      cb.onStage({ node: 'rewrite_query', label: '正在理解问题...' })
      cb.onStage({ node: 'rag_retrieve', label: '正在检索知识库...' })
      cb.onError('LLM 调用失败')
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    const trace = store.messages[1].trace!
    // onError 后 running 节点标 error；已 done 的不受影响
    expect(trace[0].status).toBe('error')  // 注意：mock 中 rewrite_query 未发 node_end
    expect(trace[1].status).toBe('error')
  })
})
