import { describe, expect, it, vi } from 'vitest'
import { consumeAskQuery } from '@/utils/askQuery'

function makeMocks(ask: unknown) {
  return {
    route: { query: { ask } },
    router: { replace: vi.fn().mockResolvedValue(undefined) },
    store: { inputText: '', sendMessage: vi.fn().mockResolvedValue(undefined) },
  }
}

describe('consumeAskQuery', () => {
  it('fills input, sends, then clears query param', async () => {
    const { route, router, store } = makeMocks('详细介绍「RAG 检索增强生成」')
    const consumed = await consumeAskQuery(route, router, store)
    expect(consumed).toBe(true)
    expect(store.inputText).toBe('详细介绍「RAG 检索增强生成」')
    expect(store.sendMessage).toHaveBeenCalledOnce()
    expect(router.replace).toHaveBeenCalledWith({ query: {} })
  })

  it('no-op when ask missing / empty / non-string', async () => {
    for (const ask of [undefined, '', '   ', 123]) {
      const { route, router, store } = makeMocks(ask)
      expect(await consumeAskQuery(route, router, store)).toBe(false)
      expect(store.sendMessage).not.toHaveBeenCalled()
      expect(router.replace).not.toHaveBeenCalled()
    }
  })
})
