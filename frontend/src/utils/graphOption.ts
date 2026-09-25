// frontend/src/utils/graphOption.ts
// ECharts 力导向图 option 构建器（纯函数，与组件解耦便于单测）。
import type { GraphData } from '@/types'

/** 5 个大类的固定配色（图例 + 节点着色共用） */
export const CATEGORY_COLORS: Record<string, string> = {
  基础架构: '#6366f1',
  检索增强: '#f59e0b',
  Agent工程: '#10b981',
  提示工程: '#ec4899',
  训练与优化: '#06b6d4',
}

export const OTHER_CATEGORY = '其他'
export const OTHER_COLOR = '#a8a29e'

/** 结构性关系（实线）；对比/相关为弱关系（虚线） */
export const STRUCTURAL_TYPES = ['依赖', '组成', '应用', '演进']

/** 度数 → 节点大小（20-60px），前端渲染前已由后端算好 degree */
export function degreeToSize(degree: number): number {
  return Math.min(60, 20 + degree * 6)
}

interface GraphParams {
  dataType: string
  data: Record<string, unknown>
}

export function buildGraphOption(
  data: GraphData,
  visibleCategories?: ReadonlySet<string>,
): Record<string, unknown> {
  const hasOther = data.nodes.some((node) => !Object.prototype.hasOwnProperty.call(CATEGORY_COLORS, node.category))
  const categoryNames = [...Object.keys(CATEGORY_COLORS), ...(hasOther ? [OTHER_CATEGORY] : [])]
  const catIndex = new Map(categoryNames.map((n, i) => [n, i]))
  const allowedCategories = visibleCategories ?? new Set(categoryNames)
  const normalizeCategory = (category: string): string =>
    Object.prototype.hasOwnProperty.call(CATEGORY_COLORS, category) ? category : OTHER_CATEGORY
  const visibleNodes = data.nodes.filter((node) => allowedCategories.has(normalizeCategory(node.category)))
  const visibleIds = new Set(visibleNodes.map((node) => node.id))

  const nodes = visibleNodes.map((n) => ({
    id: n.id,
    name: n.title,
    category: catIndex.get(normalizeCategory(n.category)) ?? 0,
    symbolSize: degreeToSize(n.degree),
    value: n.degree,
  }))

  const links = data.edges.filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target)).map((e) => ({
    source: e.source,
    target: e.target,
    type: e.type,
    description: e.description ?? '',
    lineStyle: {
      type: STRUCTURAL_TYPES.includes(e.type) ? ('solid' as const) : ('dashed' as const),
      color: '#d6d3d1',
      width: 1.5,
      curveness: 0.15,
    },
  }))

  return {
    backgroundColor: '#fafaf9',
    animation: false,
    animationDurationUpdate: 0,
    tooltip: {
      confine: true,
      formatter: (params: GraphParams) => {
        if (params.dataType === 'edge') {
          const d = params.data
          const desc = d.description ? `：${d.description}` : ''
          return `${d.type}${desc}`
        }
        if (params.dataType === 'node') {
          return `${params.data.name}（${params.data.value} 条关联）`
        }
        return ''
      },
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        force: {
          repulsion: 600,
          edgeLength: [140, 260],
          gravity: 0.05,
          layoutAnimation: false,
        },
        roam: true,
        draggable: true,
        categories: categoryNames.map((n) => ({
          name: n,
          itemStyle: { color: CATEGORY_COLORS[n] ?? OTHER_COLOR },
        })),
        data: nodes,
        links,
        label: { show: true, position: 'bottom', fontSize: 11, color: '#44403c' },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
        lineStyle: { opacity: 0.8 },
      },
    ],
  }
}
