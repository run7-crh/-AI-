# 知识图谱可视化（Knowledge Graph Visualization）设计文档

- 日期：2026-08-16
- 状态：已通过用户评审
- 关联功能：思考过程可视化（见 `2026-08-16-trace-visualization-design.md`，两功能相互独立，通过"一键提问"形成演示闭环）

## 1. 背景与动机

知识库为 AI 概念词条（`data/raw/` 下 Obsidian 格式 Markdown，实际独立概念 18 个，README 所述 20 篇含 2 个重复历史版本）。本功能目标（用户确认）：

1. **产品体验**：学习者以图谱形式浏览概念关联，点击概念发起 RAG 提问。
2. **求职展示**："LLM + 规则混合构建知识图谱" 的技术叙事，与思考过程可视化串成完整演示动线。

现有基础：

- 文档含 frontmatter（title/tags/aliases）、正文 `[[wikilink]]`、末尾"相关知识"章节——天然关系来源，但 wikilink 在入库时被 `readers.py:41-42` 剥离，关系数据未被利用。
- `frontend/package.json` 无任何图表库，需新增 ECharts。

## 2. 范围

**做**：

- 后端离线构建管线：规则（wikilink + 相关知识章节）+ LLM（隐性关系、摘要、大类）混合抽取 → `backend/data/kg.json`。
- 新 API `GET /api/graph`。
- 前端新页面 `/graph`：ECharts 力导向图 + 侧边概念卡片 + "向 Agent 提问"一键跳转聊天自动发问。

**不做（明确排除）**：

- 不做 GraphRAG（图关系注入检索上下文）——纯可视化，检索增强留作 future。
- 不做图谱手工编辑、节点增删。
- 不引入图数据库（18 节点静态产物，JSON 文件足够）。
- 不修改 `readers.py` 现有 wikilink 剥离逻辑（图谱构建独立扫 raw 目录，与向量索引互不干扰）。

## 3. 后端：构建管线（新模块 `backend/app/rag/graph_builder.py`）

构建挂在现有 `POST /api/index/rebuild` 上：索引重建成功后执行，**图谱构建失败不阻塞索引**（log warning，返回体中带 `graph_built: false` 标记）。

### 3.1 概念对齐（规则层第一步）

- 扫描 `data/raw/*.md`（跳过重复文件：同名概念仅 title/aliases 归一后取一份）。
- 归一化：`title` + `frontmatter.aliases` + 文件名 stem → 小写去空格 → 概念 ID 与展示名映射表。
- 对外目标解析：wikilink 目标或"相关知识"条目经同一归一化后若不在 18 概念清单内 → 丢弃该边（保证图内节点全部可点击、可提问）。

### 3.2 规则边抽取

- 正则抽取 `[[XXX]]` 与 `[[XXX|alias]]`（从原始正文，非入库 chunk）。
- 解析每篇末尾"相关知识"章节（标题匹配 `## .*相关知识`）下的概念条目。
- 两者均生成 `{source, target, type: "相关", via: "rule"}` 候选边。

### 3.3 LLM 抽取层（每篇 1 次调用，共 18 次，估算成本 < 1 元）

- 复用 `call_llm()`（`MODEL_FLASH`）+ `with_structured_output`，schema：

```python
class GraphExtractSchema(BaseModel):
    summary: str          # 一句话概念摘要（≤50字），用于侧边卡片
    category: Literal["基础架构", "检索增强", "Agent工程", "提示工程", "训练与优化"]
    relations: list[RelationItem]  # {target: 概念ID, type: 关系枚举, description: ≤20字}

# type 枚举：依赖 / 组成 / 对比 / 演进 / 应用 / 相关
```

- Prompt 约束：给出 18 个概念的 ID 清单，`relations.target` 必须取自清单；关系需以文档内容为依据，宁缺毋滥。
- 失败处理：单篇调用失败走现有 tenacity 重试，重试耗尽后跳过该篇（该篇仅缺 LLM 边与 summary，规则边保留；summary 缺失时前端卡片降级显示 tags）。
- temperature：0.2（抽取任务求稳定）。

### 3.4 合并与产物

- 边合并去重：`(source, target)` 无序对相同的规则边与 LLM 边合并为一条——`via` 标记 `rule`（作者确认过，可靠度更高）；`type` 采用 LLM 的细分标注（如"依赖"），仅当 LLM 未覆盖该节点对时保持规则的"相关"。
- 产出 `backend/data/kg.json`：

```json
{
  "built_at": "2026-08-16T12:00:00",
  "nodes": [{"id": "rag", "title": "RAG 检索增强生成", "summary": "...", "category": "检索增强", "tags": ["RAG"], "file": "RAG 检索增强生成.md", "degree": 7}],
  "edges": [{"source": "agent", "target": "tool-calling", "type": "依赖", "via": "rule"}]
}
```

- `degree` 为合并后度数，构建时计算，前端据此定节点大小。

## 4. API：`GET /api/graph`

- 读 `kg.json` 原样返回 `{nodes, edges, built_at}`。
- `kg.json` 不存在 → 404 `{"detail": "knowledge graph not built"}`，前端据此渲染空态 + "重建知识库"按钮（复用现有 `POST /api/index/rebuild`，已有 1/min 限速）。
- 响应带 `ETag`（取 `built_at` 哈希），支持 304，避免重复传输。

## 5. 前端：`GraphView.vue` + 路由 `/graph`

### 5.1 依赖与引入

- 新增 `echarts@5`，**按需引入**：`echarts/core` + `GraphChart` + `TooltipComponent` + `LegendComponent`（不用全量包，控制体积）。

### 5.2 图谱渲染

- 力导向布局（`layout: 'force'`，repulsion/edgeLength 按 18 节点规模调优，初始 `layoutAnimation` 提供入场动效）。
- 节点：大小按 `degree`（映射到 20-60px），颜色按 `category` 分 5 类，图例可按类筛选显隐。
- 边：线型仅分两组——结构性关系（依赖/组成/应用/演进）为实线，弱关系（对比/相关）为虚线；具体 `type` 文本在边 tooltip 中呈现，避免 6 种线型造成的视觉噪音。
- 交互：hover 高亮相邻节点（ECharts `emphasis.focus: 'adjacency'`）、边 tooltip 显示 `type + description`、拖拽节点、滚轮缩放、标签防重叠。
- 容器响应式 resize（`ResizeObserver`）。

### 5.3 侧边概念卡片

点击节点 → 右侧滑出卡片：

- `title`、`summary`（缺失时降级显示 tags）、`category` 徽章、`tags`。
- 相邻概念列表（可点击 → 图谱聚焦并切换卡片）。
- 来源文档名。
- 主按钮"**向 Agent 提问**"。

### 5.4 一键提问（两功能闭环）

- 点击按钮：构造 query = `详细介绍「{title}」`（含别名时拼 `（{aliases}）`）。
- `router.push({ path: '/chat', query: { ask: <encoded query> }})`。
- `ChatPanel` 挂载时检测 `route.query.ask` 存在且非空 → 自动填入并发送（走正常 streamChat 流程，思考过程可视化自然接管）→ 发送后清除 query 参数防刷新重发。

## 6. 数据流

```
重建索引(/api/index/rebuild) → graph_builder 扫 raw md
→ 规则边 + 概念对齐 → 18 次 LLM 抽取 → 合并去重 → kg.json
→ GET /api/graph → GraphView 力导向渲染
→ 点击节点 → 侧边卡片 → 向 Agent 提问 → /chat 自动发问 → 思考过程可视化
```

## 7. 边界与错误处理

| 场景 | 行为 |
|---|---|
| kg.json 不存在 / JSON 损坏 | API 404 / 500，前端空态 + 引导重建 |
| 单篇 LLM 抽取失败（重试耗尽） | 跳过该篇，规则边保留，summary 置空，log warning |
| wikilink 目标不在概念清单 | 丢弃该边 |
| 重复文档（raw 目录历史版本） | 概念对齐去重，仅保留一份节点 |
| 图谱构建异常 | 不阻塞索引重建主流程，响应标记 `graph_built: false` |
| 边的类型 LLM 标注非法值 | schema 校验阶段拒（structured output 保证），兜底归为"相关" |

## 8. 测试策略

- 后端单测（纯函数，重点覆盖）：wikilink/alias 正则解析、"相关知识"章节定位与条目解析、概念归一化对齐（含别名、大小写、空格）、边合并去重优先级、kg.json 读写。
- LLM 抽取：录制 fixture 测 schema 解析与失败降级，不打真实 API；真实调用走手动验收。
- 前端单测：`/api/graph` 数据 → ECharts option 的映射（category 着色、degree 大小）；`ask` query 自动发送与清除逻辑。
- 手动验收：完整动线（图谱 → 卡片 → 提问 → trace）+ 图例筛选 + 空态重建。

## 9. 依赖与参考

- 新增依赖：`echarts@5`（前端，唯一新增）；后端零新增。
- 参考实现：[react-echarts-graph（ECharts force graph + FastAPI，交互细节可参考）](https://github.com/rjalexa/react-echarts-graph)、[ECharts graph-force 官方示例](https://echarts.apache.org/examples/zh/editor.html?c=graph-force)。

## 10. Future Work（本次不做）

- GraphRAG：将图关系注入检索上下文，让答案能引用"X 与 Y 的关系"。
- 图谱随文档新增自动增量更新（当前为全量重建）。
- 点击相邻概念时展示关系边的 description 详情面板。
