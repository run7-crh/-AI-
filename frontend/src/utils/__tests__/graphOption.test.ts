import { describe, expect, it } from 'vitest'
import { buildGraphOption, CATEGORY_COLORS, degreeToSize, STRUCTURAL_TYPES } from '@/utils/graphOption'
import type { GraphData } from '@/types'

const data: GraphData = {
  built_at: '2026-08-16T00:00:00',
  nodes: [
    { id: 'a', title: 'Agent', summary: '', category: 'Agent工程', tags: [], file: 'a.md', degree: 3 },
    { id: 'b', title: 'RAG', summary: '', category: '检索增强', tags: [], file: 'b.md', degree: 1 },
    { id: 'c', title: '未知类', summary: '', category: '其他', tags: [], file: 'c.md', degree: 0 },
  ],
  edges: [
    { source: 'a', target: 'b', type: '依赖', via: 'rule' },
    { source: 'a', target: 'c', type: '相关', via: 'llm', description: '弱关联' },
  ],
}

describe('degreeToSize', () => {
  it('maps degree to size with 60px cap', () => {
    expect(degreeToSize(0)).toBe(20)
    expect(degreeToSize(3)).toBe(38)
    expect(degreeToSize(10)).toBe(60) // 封顶
  })
})

describe('buildGraphOption', () => {
  const option = buildGraphOption(data) as {
    series: Array<{
      data: Array<Record<string, unknown>>
      links: Array<Record<string, unknown>>
      categories: Array<{ name: string }>
    }>
    animation: boolean
  }

  it('maps nodes with category index and degree size', () => {
    const a = option.series[0].data.find((n) => n.id === 'a')
    expect(a?.category).toBe(2) // Agent工程 在 CATEGORY_COLORS 第 3 位
    expect(a?.symbolSize).toBe(38)
    // 未知大类归入中性“其他”类别
    const c = option.series[0].data.find((n) => n.id === 'c')
    expect(c?.category).toBe(5)
  })

  it('solid for structural types, dashed for weak', () => {
    const [dep, rel] = option.series[0].links
    expect(dep.lineStyle).toMatchObject({ type: 'solid' })
    expect(rel.lineStyle).toMatchObject({ type: 'dashed' })
    expect(rel.description).toBe('弱关联') // tooltip 数据随边携带
  })

  it('categories cover all five fixed categories', () => {
    expect(option.series[0].categories.slice(0, 5).map((item) => item.name)).toEqual(Object.keys(CATEGORY_COLORS))
    expect(STRUCTURAL_TYPES).toContain('依赖')
  })

  it('filters nodes and links by visible categories', () => {
    const filtered = buildGraphOption(data, new Set(['Agent工程'])) as {
      series: Array<{ data: Array<Record<string, unknown>>; links: Array<Record<string, unknown>> }>
    }
    expect(filtered.series[0].data.map((node) => node.id)).toEqual(['a'])
    expect(filtered.series[0].links).toHaveLength(0)
  })

  it('maps unknown categories to neutral 其他', () => {
    const other = buildGraphOption(data, new Set(['其他'])) as {
      series: Array<{ data: Array<Record<string, unknown>>; categories: Array<Record<string, unknown>> }>
    }
    expect(other.series[0].data.find((node) => node.id === 'c')).toMatchObject({ category: 5 })
    expect(other.series[0].categories[5]).toMatchObject({ name: '其他' })
  })

  it('disables continuous force relayout', () => {
    const option = buildGraphOption(data) as {
      animation: boolean
      series: Array<{ force: Record<string, unknown> }>
    }
    expect(option.animation).toBe(false)
    expect(option.series[0].force.layoutAnimation).toBe(false)
  })
})
