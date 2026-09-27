// frontend/src/types/index.ts
// 与后端 backend/app/models/schemas.py 对齐

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

export interface User {
  id: string
  username: string
  role: 'user' | 'admin'
  is_active: boolean
  created_at: string
}

export interface Credentials {
  username: string
  password: string
}

export interface Source {
  id?: string
  source_type?: 'local' | 'web' | 'attachment'
  content: string
  source: string
  title: string
  score?: number | null
  url?: string | null
  document_id?: string | null
  chunk_id?: string | null
  product_model?: string | null
  document_type?: string | null
  component?: string | null
  fault_type?: string | null
  source_id?: string | null
  data_type?: string | null
  content_truncated?: boolean
  /** 'image' = 图片观察来源（后端 attachment_evidence 标记）。 */
  media_type?: string | null
}

export type AttachmentLifecycleStatus = 'uploading' | 'pending' | 'ready' | 'failed' | 'expired' | 'deleted'
export type AttachmentExtractionStatus = 'pending' | 'ready' | 'failed' | 'skipped'

/** Public attachment metadata. The extracted body is never part of this type. */
export interface Attachment {
  id: string
  attachment_id?: string
  original_name: string
  extension: string
  declared_mime?: string | null
  detected_mime?: string | null
  size_bytes: number
  sha256?: string
  status: AttachmentLifecycleStatus
  extraction_status: AttachmentExtractionStatus
  extracted_chars?: number | null
  extraction_error?: string | null
  extraction_error_code?: string | null
  extraction_summary?: string | null
  scan_status?: string
  created_at?: string
  expires_at?: string
  deleted_at?: string | null
  /** Client-only upload progress for the current draft. */
  upload_progress?: number
  /** Client-only blob URL for image previews in the composer; never sent to the server. */
  preview_url?: string | null
}

export type AttachmentSummary = Omit<Attachment, 'sha256' | 'upload_progress'>

export interface JudgeResult {
  judge_type: string
  passed: boolean
  reason?: string
}

// 阶段 5：Agent 自动创建的工单草稿引用（仅 id/编号/状态，详情走 /api/tickets）
export interface AgentTicketRef {
  id: string
  ticket_number: string
  status: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  route_path?: string
  sources?: Source[]
  judge_log?: JudgeResult[]
  quality_warning?: string  // P1-3: 质量不合格时的警告文本
  query_log_id?: string | null  // 仅日志写入成功时可用于反馈
  safety_flag?: boolean | null
  safety_level?: string | null
  safety_situation?: string | null
  escalation_required?: boolean | null
  recommended_action?: string | null  // 阶段 5: answer/followup/create_ticket/escalate
  agent_ticket?: AgentTicketRef | null  // 阶段 5: Agent 自动创建的草稿引用
  intent?: string | null
  metadata_constraints?: Record<string, string> | null
  document_type_priority?: string[] | null
  attachments?: AttachmentSummary[] | null
  attachment_status?: AttachmentStatusPayload | null
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
  attachment_ids?: string[]
}

export interface ChatMeta {
  route_path?: string
  final_answer?: string
  sources?: Source[]
  judge_log?: JudgeResult[]
  quality_warning?: string  // P1-3: 质量警告
  query_log_id?: string | null  // 仅日志写入成功时可用于反馈
  safety_flag?: boolean | null
  safety_level?: string | null
  safety_situation?: string | null
  escalation_required?: boolean | null
  intent?: string | null
  metadata_constraints?: Record<string, string> | null
  document_type_priority?: string[] | null
  recommended_action?: string | null  // 阶段 5: 业务决策
  agent_ticket?: AgentTicketRef | null  // 阶段 5: Agent 建单草稿引用
  attachment_ids?: string[] | null
  attachment_parse_status?: string | null
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
  /** 完整答案兜底事件；流式 token 已完整到达时可忽略。 */
  onFinal?: (answer: string) => void
  onReasoning?: (text: string) => void
  onNodeEnd?: (payload: NodeEndPayload) => void
  onAttachmentStatus?: (payload: AttachmentStatusPayload) => void
  onMeta: (meta: ChatMeta) => void
  onError: (message: string) => void
  onDone: () => void
}

export interface AttachmentStatusPayload {
  phase: 'upload' | 'parse' | 'context' | 'retrieve' | 'failed'
  status: 'started' | 'ready' | 'failed'
  attachment_ids?: string[]
  count?: number
  extracted_chars?: number
  error_code?: string | null
  message?: string
}

// 知识图谱（GET /api/graph）
export interface GraphNode {
  id: string
  title: string
  summary: string
  category: string
  tags: string[]
  file: string
  degree: number
  aliases?: string[]
}

export interface GraphEdge {
  source: string
  target: string
  type: string
  via: 'rule' | 'llm'
  description?: string
}

export interface GraphData {
  built_at: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ------------------------- 售后工单（单商家第一阶段） -------------------------

export type TicketStatus =
  | 'draft'
  | 'submitted'
  | 'assigned'
  | 'in_progress'
  | 'waiting_user'
  | 'resolved_pending_confirm'
  | 'closed'
  | 'reopened'
  | 'cancelled'

export type TicketPriority = 'low' | 'normal' | 'high' | 'urgent'

export type TicketActorType = 'user' | 'admin' | 'agent' | 'system'

export interface Ticket {
  id: string
  ticket_number: string
  user_id: string
  conversation_id: string
  title: string
  problem_summary: string
  device_model: string | null
  serial_number: string | null
  firmware_version: string | null
  fault_category: string | null
  priority: TicketPriority
  safety_level: string
  escalation_reason: string | null
  assignee_user_id: string | null
  status: TicketStatus
  resolution_summary: string | null
  created_at: string
  updated_at: string
  resolved_at: string | null
  closed_at: string | null
  user_confirmed_at: string | null
}

export interface TicketEvent {
  id: string
  ticket_id: string
  actor_type: TicketActorType
  actor_id: string | null
  event_type: string
  from_status: TicketStatus | null
  to_status: TicketStatus | null
  body: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export type TicketEvidenceType = 'attachment' | 'message' | 'query_log'

export interface TicketEvidence {
  id: string
  ticket_id: string
  evidence_type: TicketEvidenceType
  evidence_id: string
  created_at: string
}

export interface TicketDetail {
  ticket: Ticket
  events: TicketEvent[]
  evidence: TicketEvidence[]
}
