// frontend/src/utils/askQuery.ts
// 知识图谱"一键提问"的落地逻辑：消费 ?ask= 参数，自动发送并清除。
// 抽为纯工具便于单测（route/router/store 由调用方注入）。
interface AskRouteLike {
  query: { ask?: unknown }
}
interface AskRouterLike {
  replace: (to: { query: Record<string, unknown> }) => Promise<unknown>
}
interface AskStoreLike {
  inputText: string
  sendMessage: () => Promise<void>
}

export async function consumeAskQuery(
  route: AskRouteLike,
  router: AskRouterLike,
  store: AskStoreLike
): Promise<boolean> {
  const ask = route.query.ask
  if (typeof ask !== 'string' || !ask.trim()) return false
  store.inputText = ask.trim()
  await store.sendMessage()
  // 清除 query 参数，防刷新重发
  await router.replace({ query: {} })
  return true
}
