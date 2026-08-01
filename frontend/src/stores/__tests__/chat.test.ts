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
      cb.onStage('正在...')
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
      cb.onMeta({ route_path: 'local', sources: [{ content: 'c', source: 'a.md', title: 'A', score: 0.9 }], judge_log: [] })
      cb.onDone()
    })

    const store = useChatStore()
    store.inputText = 'q'
    await store.sendMessage()

    expect(store.messages[1].route_path).toBe('local')
    expect(store.messages[1].sources?.length).toBe(1)
    expect(store.messages[1].sources?.[0].source).toBe('a.md')
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
})
