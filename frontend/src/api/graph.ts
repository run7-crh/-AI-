// frontend/src/api/graph.ts
// 知识图谱 API：读 kg.json / 触发重建（复用索引重建接口，1/min 限速）。
import type { GraphData } from '@/types'
import { ApiError, apiFetch } from './http'

export class GraphNotBuiltError extends Error {
  constructor() {
    super('knowledge graph not built')
    this.name = 'GraphNotBuiltError'
  }
}

export async function fetchGraph(): Promise<GraphData> {
  try {
    return (await (await apiFetch('/api/graph')).json()) as GraphData
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) throw new GraphNotBuiltError()
    throw error
  }
}

export interface RebuildResult {
  success: boolean
  doc_count: number
  vector_count: number
  graph_built: boolean
}

export async function rebuildIndex(): Promise<RebuildResult> {
  try {
    return (await (await apiFetch('/api/index/rebuild', { method: 'POST' })).json()) as RebuildResult
  } catch (error) {
    if (error instanceof ApiError && error.status === 429) {
      throw new ApiError(429, '重建请求过于频繁，请稍后再试')
    }
    throw error
  }
}
