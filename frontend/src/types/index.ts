// frontend/src/types/index.ts
// 与后端 backend/app/models/schemas.py 对齐

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface Source {
  content: string
  source: string
  title: string
  score: number
}

export interface JudgeResult {
  judge_type: string
  passed: boolean
  reason?: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  route_path?: string
  sources?: Source[]
  judge_log?: JudgeResult[]
  quality_warning?: string  // P1-3: 质量不合格时的警告文本
  query_log_id?: string  // 第 2 阶段：绑定 query_log，供反馈接口使用
  created_at: string
  // 前端运行时状态（不持久化）
  isStreaming?: boolean
  currentStage?: string
  // 思考过程可视化（不持久化，仅实时流）
  trace?: TraceNode[]
  traceStartedAt?: number
  traceDurationMs?: number
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface ChatRequest {
  conversation_id: string
  message: string
  user_label?: string  // 第 2 阶段：朋友测试时区分谁问的（如 'A'/'B'/'C'）
}

export interface ChatMeta {
  route_path?: string
  sources?: Source[]
  judge_log?: JudgeResult[]
  quality_warning?: string  // P1-3: 质量警告
  query_log_id?: string  // 第 2 阶段：供前端绑定反馈
}

// 第 2 阶段：用户反馈系统
export type FeedbackRating = 'useful' | 'useless' | 'bug'
export type UselessReason = 'irrelevant' | 'hallucination' | 'verbose' | 'wrong_route'

export interface FeedbackRequest {
  query_log_id: string
  rating: FeedbackRating
  useless_reason?: UselessReason
  comment?: string
}

export interface FeedbackResponse {
  ok: boolean
  feedback_id: string
}

export interface FeedbackStats {
  total: number
  useful_count: number
  useless_count: number
  bug_count: number
  useless_reason_breakdown: {
    irrelevant: number
    hallucination: number
    verbose: number
    wrong_route: number
  }
}

// 思考过程可视化：trace 节点与 SSE payload
export type TraceNodeStatus = 'running' | 'done' | 'error'

export interface TraceNode {
  node: string
  label: string
  status: TraceNodeStatus
  durationMs?: number
  output?: Record<string, unknown>
  reasoning?: string
}

export interface StagePayload {
  node: string
  label: string
}

export interface NodeEndPayload {
  node: string
  label: string
  duration_ms: number
  output: Record<string, unknown>
}

export interface StreamCallbacks {
  onStage: (stage: StagePayload) => void
  onToken: (token: string) => void
  onReasoning?: (text: string) => void
  onNodeEnd?: (payload: NodeEndPayload) => void
  onMeta: (meta: ChatMeta) => void
  onError: (message: string) => void
  onDone: () => void
}
