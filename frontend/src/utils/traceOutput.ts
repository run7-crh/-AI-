import type { TraceNode } from '@/types'

// output 字段的中文标签（与后端 TRACE_OUTPUT_FIELDS 白名单字段对齐）
const FIELD_LABELS: Record<string, string> = {
  rewritten_query: '改写后的问题',
  is_chitchat: '闲聊问题',
  needs_decomposition: '需要分解',
  reasoning_steps: '子问题',
  is_relevant: '知识库相关',
  retrieval_result: '检索到的文档',
  avg_reranker_score: '重排均分',
  rag_quality_pass: '检索质量通过',
  correction_count: '纠正次数',
  web_search_result: '联网搜索结果',
  has_hallucination: '疑似幻觉',
  answer_quality_pass: '答案质量通过',
  quality_warning: '质量警告',
  judge_log: '判断依据',
}

export interface OutputRow {
  label: string
  text?: string
  bool?: boolean
  number?: number
  docs?: { title: string; score?: number; content: string }[]
  steps?: string[]
}

export function outputRows(n: TraceNode): OutputRow[] {
  const rows: OutputRow[] = []
  for (const [key, value] of Object.entries(n.output ?? {})) {
    const label = FIELD_LABELS[key] ?? key
    if (key === 'retrieval_result' || key === 'web_search_result') {
      // Local retrieval emits an array while the legacy Tavily adapter emits
      // one formatted string. Normalize both shapes before rendering.
      const entries = Array.isArray(value) ? value : [value]
      rows.push({
        label,
        docs: entries.map((entry) => {
          if (!entry || typeof entry !== 'object') {
            return {
              title: key === 'web_search_result' ? '联网搜索' : '未知来源',
              content: String(entry ?? ''),
            }
          }
          const d = entry as Record<string, unknown>
          return {
            title: String(d.title ?? d.source ?? d.url ?? '未知来源'),
            score: typeof d.score === 'number' ? d.score : undefined,
            content: String(d.content ?? ''),
          }
        }),
      })
    } else if (key === 'reasoning_steps') {
      rows.push({
        label,
        steps: Array.isArray(value)
          ? value.map((step) => {
              if (step && typeof step === 'object' && 'sub_query' in step) {
                return String((step as { sub_query: unknown }).sub_query)
              }
              return String(step)
            })
          : [String(value)],
      })
    } else if (typeof value === 'boolean') {
      rows.push({ label, bool: value })
    } else if (key === 'judge_log') {
      const j = value as { raw_output?: { reason?: string }; judge_type?: string }
      rows.push({ label, text: j?.raw_output?.reason ?? j?.judge_type ?? '' })
    } else if (typeof value === 'number') {
      rows.push({ label, number: value })
    } else {
      rows.push({ label, text: String(value) })
    }
  }
  return rows
}
