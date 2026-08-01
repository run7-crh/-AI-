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
  created_at: string
  // 前端运行时状态（不持久化）
  isStreaming?: boolean
  currentStage?: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
}

export interface ChatRequest {
  conversation_id: string
  message: string
}

export interface ChatMeta {
  route_path?: string
  sources?: Source[]
  judge_log?: JudgeResult[]
  quality_warning?: string  // P1-3: 质量警告
}

export interface StreamCallbacks {
  onStage: (stage: string) => void
  onToken: (token: string) => void
  onMeta: (meta: ChatMeta) => void
  onError: (message: string) => void
  onDone: () => void
}
