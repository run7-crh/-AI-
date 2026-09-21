// frontend/src/api/feedback.ts
// 第 2 阶段：用户反馈系统 API
import type { FeedbackRequest, FeedbackResponse, FeedbackStats } from '@/types'
import { apiFetch } from './http'

async function ensureOk(r: Response): Promise<Response> {
  return r
}

/**
 * upsert 用户反馈（幂等）。
 * - rating='useless' 时 useless_reason 必填
 * - 同一 query_log_id 多次调用走更新语义
 */
export async function putFeedback(req: FeedbackRequest): Promise<FeedbackResponse> {
  const r = await apiFetch('/api/feedback', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  await ensureOk(r)
  return r.json()
}

/**
 * 获取反馈统计数据（供后台查看整体分布）。
 */
export async function getFeedbackStats(): Promise<FeedbackStats> {
  const r = await apiFetch('/api/feedback/stats')
  await ensureOk(r)
  return r.json()
}
