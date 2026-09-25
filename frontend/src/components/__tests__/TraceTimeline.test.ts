import { describe, expect, it } from 'vitest'
import { outputRows } from '@/utils/traceOutput'

describe('TraceTimeline outputRows', () => {
  it('normalizes legacy string web search output without throwing', () => {
    const rows = outputRows({
      node: 'web_search',
      label: '联网搜索',
      status: 'done',
      output: { web_search_result: '[1] 搜索结果' },
    })

    expect(rows[0].docs).toEqual([
      { title: '联网搜索', content: '[1] 搜索结果' },
    ])
  })

  it('keeps structured retrieval results unchanged', () => {
    const rows = outputRows({
      node: 'rag_retrieve',
      label: '检索',
      status: 'done',
      output: {
        retrieval_result: [{ title: 'RAG.md', content: '内容', score: 0.8 }],
      },
    })

    expect(rows[0].docs?.[0]).toEqual({ title: 'RAG.md', content: '内容', score: 0.8 })
  })

  it('renders structured decomposition steps as query text', () => {
    const rows = outputRows({
      node: 'decompose_question',
      label: '分解',
      status: 'done',
      output: { reasoning_steps: [{ sub_query: '什么是 RAG' }] },
    })

    expect(rows[0].steps).toEqual(['什么是 RAG'])
  })
})
