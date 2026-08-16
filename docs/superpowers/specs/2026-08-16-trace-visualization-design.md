# 思考过程可视化（Trace Visualization）设计文档

- 日期：2026-08-16
- 状态：已通过用户评审
- 关联功能：知识图谱可视化（见 `2026-08-16-knowledge-graph-design.md`，两功能相互独立）

## 1. 背景与动机

项目是 AI 领域知识学习助手的垂直 PoC。本功能目标（用户确认）：

1. **产品体验**：让学习者看到 Agent 如何思考（当前节点、中间结果、路由决策），理解而非黑盒。
2. **求职展示**：面试演示时呈现"类 LangSmith trace 嵌入聊天界面"的技术叙事。

现有基础：

- `backend/app/api/chat.py:110-138` 已用 `graph.astream_events(version="v2")` 消费事件，但 `on_chain_end`（name=具体节点）携带的节点 output dict 目前被丢弃。
- SSE 协议已有 5 种事件（stage/token/meta/error/done），前端 `frontend/src/api/chat.ts` 以 fetch + ReadableStream 解析并分发。
- `frontend/src/components/StageIndicator.vue` 只有 9 个圆点进度条，与后端 `STAGE_LABELS` 双份手工维护。

## 2. 范围

**做**：

- 后端新增 2 种 SSE 事件（`node_end`、`reasoning`），`stage` 事件 data 结构升级。
- 前端新组件 `TraceTimeline.vue` 替代 `StageIndicator.vue`：流式期间逐节点展开动画 + 中间结果查看，完成后折叠为一行"已深度思考"。
- 捞回 deepseek-reasoner 的 `reasoning_content` 原始思维流，在 `multi_step_reason` 节点展开时展示。

**不做（YAGNI，明确排除）**：

- trace 不持久化：只存在于实时流，历史会话仅回放最终答案（future work）。
- 不做嵌套树/任意深度通用 trace 协议（LangGraph 节点单层，无嵌套场景）。
- 不接入 LangSmith/LangFuse 等外部平台。
- 不改动 LangGraph 图结构、节点逻辑、评估链路本身。

## 3. SSE 事件协议（5 种 → 7 种）

| 事件 type | 触发 | data 结构 | 状态 |
|---|---|---|---|
| `stage` | `on_chain_start`（name=节点名） | `{node: string, label: string}`（原为裸 string，**结构变更**） | 改造 |
| `node_end` | `on_chain_end`（name=节点名，排除 LangGraph 总节点） | `{node, label, duration_ms: int, output: object}` | 新增 |
| `reasoning` | `on_chat_model_stream` 且 chunk 含 reasoning_content | string（增量文本） | 新增 |
| `token` / `meta` / `error` / `done` | 不变 | 不变 | 保持 |

前后端同仓库同步发版，`stage` 结构变更为 breaking change 但无外部消费者。

### 3.1 耗时统计

事件循环内维护 `{node_name: start_timestamp}` 字典：`on_chain_start` 记录，`on_chain_end` 计算差值得 `duration_ms`。CRAG 回路中同名节点多次执行，字典按事件顺序覆盖即可（start 总是先于对应 end）。

### 3.2 `node_end` 的 output 白名单

13 个节点各取关键中间字段（字段名以 `nodes.py` 实际返回为准，已逐个核对）：

| 节点 | output 字段 | 前端展示 |
|---|---|---|
| `rewrite_query` | `rewritten_query` | 改写后的问题 |
| `decompose_question` | `is_chitchat`, `needs_decomposition`, `reasoning_steps` | 意图分类结论 + 子问题列表 |
| `chitchat_node` | —（无白名单字段） | 仅名称+耗时 |
| `judge_relevance` | `is_relevant`, `judge_log[-1].raw_output.reason` | 相关性结论 + 判断依据/短路方式 |
| `rag_retrieve` | `retrieval_result`（每条 content 截断 200 字）, `avg_reranker_score` | 检索文档列表 + 重排均分 |
| `rag_quality_eval` | `rag_quality_pass`, `judge_log[-1].raw_output` | 质量结论 + 短路/LLM 判断详情 |
| `query_corrector` | `rewritten_query`, `correction_count` | 纠正后的 query |
| `web_search` | `web_search_result`（每条截断 200 字） | 联网搜索结果列表 |
| `generate_local` / `generate_online` | —（正文走 token 流） | 仅名称+耗时 |
| `multi_step_reason` | —（正文走 token/reasoning 流） | 仅名称+耗时 |
| `combined_quality_check` | `has_hallucination`, `answer_quality_pass`, `judge_log[-1].raw_output` | 幻觉/质量双结论 |
| `quality_fail` | `quality_warning` | 质量警告文案 |

白名单外的 output 字段一律不下发（控制 payload 体积、避免泄露内部 state）。

### 3.3 reasoning 事件机制

- 实现位置：`chat.py` 的 `on_chat_model_stream` 分支。langchain-openai 会把 DeepSeek 的思维链透传在 chunk 的 `additional_kwargs.reasoning_content`（**实现时需实测确认字段名**，不同版本可能为顶层属性）。
- 降级行为：字段缺失或为空 → 不发 `reasoning` 事件，该节点展开区无思维流，**不报错**。只有 `multi_step_reason`（deepseek-reasoner）会产生该字段，其余节点（deepseek-chat）天然没有。
- **不改 `tools.py`**：其流式聚合仍只取 `chunk.content` 作为答案正文，reasoning_content 的消费完全在 `chat.py` 事件层。

## 4. 前端设计

### 4.1 数据层改动

- `frontend/src/types/index.ts`：新增 `TraceNode` 类型 `{node, label, status: 'running'|'done'|'error', durationMs?: int, output?: object, reasoning?: string}`；SSE 事件类型联合扩充。
- `frontend/src/api/chat.ts`：`dispatchEvent` 增加 `reasoning` → `onReasoning`、`node_end` → `onNodeEnd` 分支；`onStage` 签名适配新 data 结构。
- `frontend/src/stores/chat.ts`：assistant 消息增加 `trace: TraceNode[]`；回调将事件映射为 trace 状态机更新（`stage` → push running 节点；`node_end` → 最新同名 running 节点置 done + 填充 output/duration；`reasoning` → 累加到当前 running 节点的 reasoning；`error` → 当前 running 节点置 error）。

### 4.2 TraceTimeline 组件（新，替代并删除 StageIndicator.vue）

流式期间（消息 status=streaming）：

- 垂直 timeline，节点行随 `stage` 事件逐个出现（slide-in 动画）；当前节点 spinner，完成节点打勾 + 耗时徽章（如 `1.2s`）。
- 节点行默认折叠，点击展开中间结果区（output 白名单字段的友好渲染：query 文本、文档列表带来源与分数、评估结论徽章）。
- `multi_step_reason` 节点展开区顶部显示原始思维流（灰色小字等宽字体，随 `reasoning` 事件实时 append，自动滚动到底）。
- CRAG 回路（`rag_retrieve`/`rag_quality_eval`/`query_corrector` 第二次执行）显示为同名第二个节点行——刻意保留，是演示架构回路的亮点。

完成后（`done` 事件）：

- 整个 timeline 折叠为一行按钮样式："已深度思考（用时 Xs · N 个节点）"，X 为前端记录的挂钟时间（首个 `stage` 事件到 `done` 事件），非节点耗时简单相加。
- 点击展开回看完整 trace，再点折叠。

错误态（`error` 事件）：

- timeline 停止追加，当前 running 节点标红 + 错误图标，保持展开可回看。

动画实现：Tailwind transition（enter/leave），不引入动画库。

### 4.3 历史消息

历史 assistant 消息无 trace 字段 → 不渲染 TraceTimeline（与现状一致，仅显示答案 + 已有的 SourceCard/JudgeBadges）。

## 5. 事件序列示例（分解路径）

```
stage{node:rewrite_query} → node_end{rewritten_query}
→ stage{decompose_question} → node_end{is_chitchat:false, needs_decomposition:true, reasoning_steps:[...]}
→ stage{multi_step_reason} → reasoning×N → token×N → node_end{...}
→ stage{combined_quality_check} → node_end{has_hallucination:false, answer_quality_pass:true}
→ meta{route_path, sources, judge_log, ...} → done（折叠）
```

## 6. 边界与错误处理

| 场景 | 行为 |
|---|---|
| 客户端中途断开 | 现有 `finally` + `asyncio.shield` 落库逻辑不变，trace 仅影响 SSE 层 |
| CRAG 回路重复执行同名节点 | trace 追加第二个同名节点行，按事件顺序配对 |
| `on_chain_end` 的 output 无白名单字段 | `output` 为空对象，节点行仅显示名称+耗时 |
| reasoning_content 字段不存在（版本差异） | 静默降级，无思维流展示 |
| 图执行异常 | `error` 事件 → 当前节点标红，不影响答案区已有内容 |
| node_end payload 体积 | retrieval_result/web_search_result 每条 content 截断 200 字符 |

## 7. 测试策略

- 后端：`chat.py` 事件循环单测——mock `astream_events` 事件序列（含回路、异常、缺 reasoning 字段），断言 SSE 输出的事件顺序与 payload 白名单过滤、截断、耗时计算。
- 前端单测：`chat.ts` 7 种事件解析分发；store 的 trace 状态机（事件序列 → TraceNode[] 状态）。
- 手动验收：闲聊/本地 RAG/CRAG 纠正回路/联网/分解五条路径各跑一遍，核对节点行、展开内容、折叠行为、思维流滚动。

## 8. 依赖与参考

- 新增依赖：无（纯增量）。
- 参考实现：[langgraph-agentic-scaffold 的 SSE node_start/node_end + thought stream 模式](https://github.com/shanevcantwell/langgraph-agentic-scaffold/blob/main/docs/WEB_UI.md)。

## 9. Future Work（本次不做）

- trace 持久化到 query_log，历史会话回放完整思考过程。
- 节点耗时统计聚合（P95、瓶颈节点分析）。
- 多轮对话的 trace 对比视图。
