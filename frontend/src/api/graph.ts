// frontend/src/api/graph.ts
// 知识图谱 API：读 kg.json / 触发重建（复用索引重建接口，1/min 限速）。
import type { GraphData } from '@/types'

export class GraphNotBuiltError extends Error {
  constructor() {
    super('knowledge graph not built')
    this.name = 'GraphNotBuiltError'
  }
}

export async function fetchGraph(): Promise<GraphData> {
  const r = await fetch('/api/graph')
  if (r.status === 404) throw new GraphNotBuiltError()
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()) as GraphData
}

export interface RebuildResult {
  success: boolean
  doc_count: number
  graph_built: boolean
}

export async function rebuildIndex(): Promise<RebuildResult> {
  const r = await fetch('/api/index/rebuild', { method: 'POST' })
  if (r.status === 429) throw new Error('重建请求过于频繁，请稍后再试')
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return (await r.json()) as RebuildResult
}
