# RAG Agent 项目复盘（历史记录）

## 一、项目定位

**一句话定位**：无人机智能售后技术支持 Agent，基于 LangGraph 的安全优先 Corrective RAG 原型。

> 本文包含早期迭代记录和旧版评估结果。当前代码没有 Tool Calling、ReAct 循环或模型自主工具选择；知识图谱只用于可视化，不参与 Graph RAG。旧版关键词命中率、非空检索率和路由百分比不能直接证明当前 RAG 质量。请以 `backend/eval/dataset.json` v1.2 及新生成报告为准。

**核心目标**：展示"数据驱动闭环优化"能力，不是做通用 Agent。

项目价值不在于功能多复杂，而在于：
1. 建立了可复核的评估框架（Recall/MRR 仅在有文档标注时计算）
2. 预留真实用户数据的反馈闭环；当前仓库评估集仍为 seed，真实用户评估尚未完成
3. 每一轮优化都有数据支撑和验证（可量化、可复现）

---

## 二、技术架构（简述）

### LangGraph 节点拓扑

```
START → rewrite_query → decompose_question
         ├─ is_chitchat → chitchat_node → END
         ├─ needs_decomposition → multi_step_reason → combined_quality_check → END
         └─ else → judge_relevance
                    ├─ relevant → rag_retrieve → rag_quality_eval
                    │               ├─ pass → generate_local → combined_quality_check → END
                    │               └─ fail → query_corrector → rag_retrieve (CRAG 回路)
                    │                          (correction_count < 1)
                    └─ not_relevant → web_search → generate_online → combined_quality_check → END
```

### 4 条执行路径

1. **chitchat**：闲聊快速通道，跳过质量检查
2. **local**：本地知识库检索生成（理想路径）
3. **online**：联网搜索生成（知识库无关或检索失败）
4. **decomposition**：多步分解推理（对比类/并列子问题）

### CRAG 纠正回路

当 `rag_quality_eval` 失败时，不直接走 `web_search`，而是通过 `query_corrector` 二次改写查询重试一次。`correction_count` 上限 1 次，防死循环。

**关键设计**：
- `query_corrector` 职责不同于首次 `rewrite_query`：解决"检索方向错误"，回传失败原因给 LLM
- 与首次改写的区别：首次解决指代消解/补上下文，纠正解决检索方向偏差

---

## 三、数据驱动优化闭环（核心章节）

### 3.1 评估体系搭建

**为什么建评估体系**

没有评估的迭代是盲改。我看到太多人做 RAG 项目，优化全靠"感觉"——改个 prompt 觉得好了，跑几个 case 觉得没问题，实际上是在过拟合自己的直觉。

我的做法：
1. 先建评估集和指标，再开始优化
2. 每轮优化前后都跑评估，用数据说话
3. 计划区分"自测基线"和"真实用户数据"，避免把未完成的真实用户评估写成结论

**早期 v1.1 自测评估集设计：5 类问题（20 条）**

| 类别 | 数量 | 说明 | 示例 |
|------|------|------|------|
| `knowledge_hit` | 4 | 知识库已有内容 | "什么是 RAG" |
| `knowledge_missing` | 4 | 知识库缺失，需联网 | "2026 最新 RAG 框架" |
| `multi_hop` | 4 | 多步推理 | "RAG 和 Fine-tuning 的区别" |
| `routing_test` | 4 | 路由判断 | 闲聊、关联问题 |
| `hallucination_test` | 4 | 幻觉测试 | 知识库未提及的细节 |

难度分布：easy 6 条，medium 8 条，hard 6 条。

**当前评估指标定义（dataset v1.2）**

1. **route_accuracy**：路由准确率（实际路径是否在 `acceptable_routes` 中）
2. **retrieval_recall_at_1/3/5**：`expected_documents` 在对应 Top-K 中的文档级 Recall；只对 `expected_documents` 非空的题计算，其中 `gold_status=inferred` 尚未全部人工复核
3. **retrieval_mrr / retrieval_ndcg_at_1/3/5**：相关文档排序质量指标
4. **citation_correctness**：答案文本的显式来源标记是否命中至少一个预期文档名；不等同于事实级引用正确性，多文档题不等同于全部来源都正确。兼容字段 `source_correct` 仍表示检索结果是否命中预期文档
5. **answer_relevance / answer_f1**：仅当题目提供 `reference_answer` 时计算 lexical token F1
6. **keyword_coverage**：显式开启时的关键词覆盖率，仅作辅助诊断
7. **route_accuracy / latency_ms**：路由命中率和响应延迟

Recall/MRR 统计的是 API 最终返回的本地 Evidence，不是独立 Retriever 的原始候选集；普通 local 路径最多返回 3 条证据，因此 Recall@5 在该路径上不会比 Recall@3 多出结果。当前数据没有独立的 `expected_hallucination` 真值，`hallucination_count` 只能反映 API 的结构化模型判断，不能解释为幻觉检测准确率。

`retrieval_success_rate` 是历史兼容字段，当前固定为 `null`；旧版关键词命中率、非空检索率和“无来源即幻觉”规则不再用于质量结论。

**数据来源说明**

当前 `dataset.json` 共 99 条 seed 问题，其中 71 条为 `gold_status=inferred`、28 条为 `unlabeled`；前者尚未全部人工复核，后者不进入 Recall/MRR 分母。题目没有 `reference_answer` 时，答案 F1 会显示为 N/A。

### 3.2 第一轮：自测基线与优化

**基线指标（早期 v1.1 历史报告，08-02 16:33，20 条）**

| 指标 | 数值 |
|------|------|
| route_accuracy | {{0.95}} |
| answer_relevance | {{1.0}} |
| source_correctness | {{0.67}} |
| retrieval_success_rate（deprecated） | {{1.0}} |
| hallucination_count | {{1}} |

**发现的 3 个问题**

**问题 1（P0）：时效性问题误路由**

- **数据证据**：q005 "2026年最新的开源 RAG 框架有哪些？" 期望路由 `online`，实际走了 `local`
- **根因分析**：`judge_relevance` 节点用 LLM 判断相关性，LLM 把"2026 最新"误判为通用知识，没有识别出时效性需求
- **改动方案**：在 `judge_relevance` 前增加时效性关键词检测，命中"最新/今天/2024/2025/2026"等关键词的问题强制走 `online`
- **验证结果**：08-03 报告中 q005 正确路由到 `online`，route_accuracy 提升到 {{1.0}}

**问题 2（P1）：答案开头复述 query**

- **数据证据**：多个答案以"什么是 RAG？RAG 是..."开头，复述用户问题
- **根因分析**：`LOCAL_GEN_PROMPT` 没有明确禁止复述 query
- **改动方案**：在 prompt 中增加约束："禁止在回答开头重复或复述用户问题，直接给出答案"
- **验证结果**：后续答案不再复述 query，直接以"RAG 是..."开头

**问题 3（P2）：搜索失败无 warning**

- **数据证据**：`generate_online` 节点在 Tavily 搜索失败时，仍生成答案但无提示
- **根因分析**：搜索失败时返回空字符串，LLM 基于空内容生成，用户不知道信息可能不完整
- **改动方案**：检测搜索失败标识，设置 `quality_warning` 字段，前端展示黄色警告横幅
- **验证结果**：搜索失败时前端展示"联网搜索失败，已基于有限信息生成回答，建议稍后重试"

**优化后指标（早期 v1.1 历史报告，08-03 22:27，20 条）**

| 指标 | 数值 | 变化 |
|------|------|------|
| route_accuracy | {{1.0}} | +0.05 |
| answer_relevance | {{1.0}} | 0 |
| source_correctness | {{1.0}} | +0.33 |
| retrieval_success_rate（deprecated） | {{1.0}} | 0 |
| hallucination_count | {{0}} | -1 |

**反思**

20 条自测 100% 不可信。问题：
1. 评估集是手写的，可能覆盖了所有边界 case
2. 自己测试时会下意识避开"刁钻"问题
3. 没有真实用户的使用场景和提问习惯

后续计划引入朋友测试，收集真实数据；该计划在当前仓库中尚未完成。

### 3.3 朋友测试（历史计划，当前未完成）

当前 `dataset.json` 的 `source_distribution` 为 `seed=99`、`from_query_log=0`，没有可用于发布指标的真实用户评估集。

**计划中的测试规模**

- 人数：{{待补充}} 人
- 测试周期：{{待补充}} 周
- 测试方式：Cloudflare Tunnel 内网穿透，新会话独立测试

**计划中的数据收集**

- query_log 条数：{{待补充}} 条请求
- feedback 条数：{{待补充}} 条反馈（点赞/点踩/评论）

**计划中的测试方式**

1. 用 Cloudflare Tunnel 把本地 8000 端口暴露到公网
2. 朋友通过公网 URL 访问，每次测试新建会话
3. 不限制提问内容，鼓励问真实问题
4. 前端增加反馈按钮（点赞/点踩/评论），收集主观评价

**预期发现的问题（当前无 query_log + feedback 证据）**

计划在收集数据后列出，当前没有可填入的真实案例：

1. **问题 1**：{{待补充}}
   - 数据证据：{{待补充}}
   - 影响范围：{{待补充}}

2. **问题 2**：{{待补充}}
   - 数据证据：{{待补充}}
   - 影响范围：{{待补充}}

3. **问题 3**：{{待补充}}
   - 数据证据：{{待补充}}
   - 影响范围：{{待补充}}

**评估集更新计划（当前未执行）**

基于真实用户数据，替换 40% 评估集为真实问题。替换原则：
1. 选择 feedback 为"点踩"的问题
2. 选择 query_log 中 `route_path` 与期望不符的问题
3. 选择答案被标记为"有幻觉"的问题

### 3.4 第二轮：真实数据驱动优化（历史计划，当前未完成）

**基线指标（第 3 轮报告，更新后的评估集）**

| 指标 | 数值 |
|------|------|
| route_accuracy | {{待补充}} |
| answer_relevance | {{待补充}} |
| source_correctness | {{待补充}} |
| retrieval_success_rate（deprecated） | {{待补充}} |
| hallucination_count | {{待补充}} |

**基于数据选 1-2 个最差点优化**

**优化 1：{{待补充}}**

- **数据证据**：{{待补充}}（具体 SQL 查询结果）
  ```sql
  -- 示例：统计路由错误分布
  SELECT route_path, COUNT(*) as count
  FROM query_log
  WHERE route_path != expected_route
  GROUP BY route_path
  ORDER BY count DESC;
  ```
- **改动**：{{待补充}}
- **验证**：{{待补充}}

**优化 2：{{待补充}}**

- **数据证据**：{{待补充}}
- **改动**：{{待补充}}
- **验证**：{{待补充}}

**优化后指标（第 4 轮报告）**

| 指标 | 数值 | 变化 |
|------|------|------|
| route_accuracy | {{待补充}} | {{待补充}} |
| answer_relevance | {{待补充}} | {{待补充}} |
| source_correctness | {{待补充}} | {{待补充}} |
| retrieval_success_rate（deprecated） | {{待补充}} | {{待补充}} |
| hallucination_count | {{待补充}} | {{待补充}} |

**2 轮优化对比表（前两轮为 v1.1 历史自测；后两轮仍是计划）**

| 轮次 | 评估集 | route_accuracy | source_correctness | hallucination_count | 关键改进 |
|------|--------|----------------|--------------------|--------------------|---------| 
| 第 1 轮（v1.1 历史基线） | 20 条手写 | {{0.95}} | {{0.67}} | {{1}} | - |
| 第 2 轮（v1.1 历史自测优化） | 20 条手写 | {{1.0}} | {{1.0}} | {{0}} | 时效性路由、prompt 约束 |
| 第 3 轮（真实数据基线） | {{待补充}} | {{待补充}} | {{待补充}} | {{待补充}} | 替换 40% 真实问题 |
| 第 4 轮（真实数据优化） | {{待补充}} | {{待补充}} | {{待补充}} | {{待补充}} | {{待补充}} |

### 3.5 闭环总结

**4 轮评估的指标变化曲线表（前两轮为 v1.1 历史记录，后两轮未完成）**

| 轮次 | route_accuracy | source_correctness | hallucination_count | 平均延迟 (ms) |
|------|----------------|--------------------|--------------------|--------------|
| 第 1 轮 | {{0.95}} | {{0.67}} | {{1}} | {{待补充}} |
| 第 2 轮 | {{1.0}} | {{1.0}} | {{0}} | {{待补充}} |
| 第 3 轮 | {{待补充}} | {{待补充}} | {{待补充}} | {{待补充}} |
| 第 4 轮 | {{待补充}} | {{待补充}} | {{待补充}} | {{待补充}} |

**哪些优化有效、哪些无效**

有效：
1. 时效性关键词检测：route_accuracy 从 0.95 提升到 1.0
2. prompt 约束（禁止复述 query）：答案质量明显提升
3. {{待补充}}

无效或效果不明显：
1. {{待补充}}
2. {{待补充}}

**数据驱动 vs 经验驱动的差异**

经验驱动的问题：
- 容易过拟合自己的直觉
- 优化方向可能偏离真实需求
- 无法量化改进效果

数据驱动的优势：
- 目标是用真实用户行为发现问题（当前真实用户评估尚未完成）
- 每轮优化都有量化指标
- 可以复现和验证

---

## 四、已知局限

### 局限 1：评估数据仍有限，且 gold 未完全复核

**问题现象**

早期 v1.1 的 20 条评估集即使 100% 准确，置信区间也很宽。当前 v1.2 扩展到 99 条 seed 问题，但其中 71 条 `expected_documents` 仍是 `gold_status=inferred`，28 条为 `unlabeled`，因此不能把当前结果当作已人工验证的基准。

**根因分析**

1. 个人项目，没有足够资源构建大规模评估集
2. 手写评估集耗时，每条需要设计期望路由、关键词、来源
3. 当前评估集尚未接入真实用户数据（`from_query_log=0`）

**如果继续做的优化思路**

1. 用 LLM 批量生成评估问题（给定知识库内容，自动生成 5 类问题）
2. 引入人工标注平台（如 Amazon Mechanical Turk），快速扩充评估集
3. 建立持续评估机制：每次部署后自动跑评估，监控指标漂移

### 局限 2：无认证和权限隔离，无法多租户

**问题现象**

API 无认证，任何人知道 URL 就能访问。CORS 写死 `localhost`，无法部署到公网供多人使用。

**根因分析**

1. 设计文档明确"不做用户系统/权限隔离"（非目标）
2. 个人项目，优先保证核心功能完整
3. 认证机制涉及用户管理、会话管理、权限模型，复杂度高

**如果继续做的优化思路**

1. 最简方案：API Key 认证（每个用户分配唯一 key，请求时校验）
2. 中等方案：JWT Token（用户登录后颁发 token，前端存储并每次请求携带）
3. 完整方案：OAuth 2.0（支持第三方登录，如 GitHub/Google）

### 局限 3：单知识库硬编码，无法扩展

**问题现象**

当前只支持单个知识库目录（`data/raw`），无法同时检索多个知识库。

**根因分析**

1. 设计文档明确此为"非目标"
2. 单知识库已满足个人需求
3. 多知识库涉及索引管理、路由策略、结果融合，复杂度高

**如果继续做的优化思路**

1. 配置化：在 `config.py` 中支持多个知识库路径，每个知识库独立索引
2. 路由策略：根据问题内容自动选择知识库（如"RAG 相关"走 AI 知识库，"股票相关"走金融知识库）
3. 结果融合：多知识库检索结果按 reranker 分数统一排序，取 top-k

---

## 五、指标证明

**当前指标证明（dataset v1.2）**

| 指标 | 当前状态 |
|------|----------|
| route_accuracy | 运行 `python eval/run_eval.py` 后生成 |
| retrieval_recall_at_1/3/5 | 仅对 `expected_documents` 非空题计算；71 条为 inferred，28 条 unlabeled 不入分母 |
| retrieval_mrr / nDCG@K | 仅对有文档标注的题计算 |
| answer_relevance / answer_f1 | 当前 N/A（未提供 `reference_answer`） |
| hallucination_count | 仅消费结构化质量事件，缺失时不推断；无独立 hallucination gold，不能计算检测准确率 |
| 平均延迟 (ms) | 运行报告记录 |

**评估集规模**

- 总条数：99 条（seed；71 条 `gold_status=inferred`，28 条 `unlabeled`）
- 5 类问题分布：knowledge_hit 40 条，knowledge_missing 19 条，multi_hop 20 条，routing_test 10 条，hallucination_test 10 条
- 难度分布：easy 27 条，medium 42 条，hard 30 条

**用户规模**

- 测试人数：{{待补充}} 人
- 测试周期：{{待补充}} 周
- query_log 条数：{{待补充}} 条
- feedback 条数：{{待补充}} 条

---

## 六、技术决策回顾

### 决策 1：用 reranker 分数短路 vs 纯 LLM 判断

**决策内容**

在 `judge_relevance` 和 `rag_quality_eval` 节点，用 reranker 分数阈值短路，而不是全部交给 LLM 判断。

**备选方案**

1. 纯 LLM 判断：所有相关性/质量判断都调 LLM
2. 纯 reranker 判断：只用 reranker 分数，不调 LLM
3. 混合方案（选择）：reranker 高分/低分短路，灰色地带调 LLM

**选择理由**

1. 成本：LLM 调用贵（DeepSeek API 按 token 计费），能省则省
2. 延迟：LLM 调用慢（1-3 秒），reranker 本地推理快（<100ms）
3. 准确性：reranker 在高分/低分区间的判断与 LLM 一致率高，灰色地带才需要 LLM 精细判断

**阈值设定**

- `judge_relevance`：`top_k=1` reranker 分数 >= 0.5 直接判 `relevant=true`
- `rag_quality_eval`：`avg_score > 0.7` 通过，`avg_score < 0.3` 不通过，0.3-0.7 调 LLM

**结果验证**

08-02 到 08-03 的历史报告中，短路机制生效；在对应的典型完整路径上，LLM 调用次数从 6 次降到 5 次，延迟降低 {{待补充}}%。实际调用次数会随闲聊、阈值短路和 CRAG 重试而变化。

### 决策 2：合并质量评估（1 次 LLM）vs 串行评估（2 次 LLM）

**决策内容**

将 `hallucination_check` 和 `answer_quality_eval` 合并为 `combined_quality_check`，一次 LLM 调用同时评估幻觉和答案质量。

**备选方案**

1. 串行评估：先调 LLM 检测幻觉，再调 LLM 评估答案质量（2 次调用）
2. 合并评估（选择）：一次 LLM 调用同时评估两个维度

**选择理由**

1. 成本：在典型完整路径上，合并后 LLM 调用从 6 次降到 5 次；实际次数随路由、短路和重试变化
2. 延迟：减少 1 次 LLM 调用，延迟降低 1-2 秒
3. 准确性：两个评估任务的 prompt 可以合并，LLM 在一次调用中同时考虑两个维度，判断更一致

**结果验证**

08-03 报告中，`combined_quality_check` 节点正常工作，幻觉检测和答案质量评估都准确。

### 决策 3：CRAG 纠正 1 次 vs 多次

**决策内容**

`query_corrector` 节点在 `rag_quality_eval` 失败时重试一次，`correction_count` 上限 1 次。

**备选方案**

1. 不纠正：检索失败直接走 `web_search`
2. 纠正 1 次（选择）：重试一次，仍失败走 `web_search`
3. 纠正多次：重试 N 次，直到成功或达到上限

**选择理由**

1. 不纠正的问题：浪费本地知识库，有些问题稍作改写就能检索到
2. 纠正多次的问题：死循环风险，且多次纠正后仍失败说明问题本身不适合本地知识库
3. 纠正 1 次的平衡：给一次机会，但不过度消耗

**结果验证**

08-03 报告中，`correction_count` 字段正常工作，未出现死循环。具体纠正成功次数 {{待补充}}。

### 决策 4：Cloudflare Tunnel vs 云服务器部署

**决策内容**

用 Cloudflare Tunnel 内网穿透，而不是部署到云服务器。

**备选方案**

1. 云服务器部署：购买阿里云/腾讯云 ECS，部署后端
2. Cloudflare Tunnel（选择）：本地运行，通过 Tunnel 暴露到公网

**选择理由**

1. 成本：云服务器按月收费（最低 50-100 元/月），Cloudflare Tunnel 免费
2. 便利性：本地开发调试方便，不需要每次改代码都部署到服务器
3. 性能：个人项目流量小，Tunnel 性能足够

**结果验证**

该部署方案仅作为历史计划记录；当前仓库没有可核验的朋友测试运行数据。

---

## 七、收获与反思

### 做对了什么

1. **先建评估体系，再开始优化**

   没有评估的迭代是盲改。我先设计了 5 类问题和 6 项指标，确保每轮优化都有数据支撑。

2. **区分自测和真实用户数据**

   自测 100% 不可信。项目预留了朋友测试和反馈闭环，但当前仓库尚未接入真实用户评估（`from_query_log=0`），因此不能把这部分写成已完成结果。

3. **每一轮优化都有数据证据和验证**

   不是"我觉得好了"，而是"数据显示 route_accuracy 从 0.95 提升到 1.0"。

4. **诚实面对已知局限**

   不回避问题，明确列出 3 个未解决的局限，并给出如果继续做的优化思路。

### 做错了什么

1. **评估集规模太小**

   早期 v1.1 的 20 条评估集统计意义有限，95% 置信区间宽。当前 v1.2 虽扩展到 99 条，但 gold 仍未全部人工复核，应该继续用人工标注和真实用户数据扩充。

2. **朋友测试周期太短**

   {{待补充}} 周的测试周期，收集的 query_log 和 feedback 数据有限。应该延长到 {{待补充}} 周，或增加测试人数。

3. **优化方向可能偏离**

   基于 20 条自测数据优化，可能过拟合了手写评估集。应该更早引入真实用户数据，避免自嗨。

### 如果重来会怎么改

1. **第一天就建评估体系**

   不是"功能做完了再补评估"，而是"先有评估，再有功能"。

2. **更早引入真实用户**

   不是"自测 100% 了再找人测"，而是"功能基本可用就找人测"。真实用户数据比自测更有价值。

3. **建立持续评估机制**

   不是"跑 4 轮评估就结束"，而是"每次部署后自动跑评估，监控指标漂移"。

4. **量化每一分钱的成本**

   记录每次 LLM 调用的 token 消耗和费用，计算每次请求的平均成本。这样能更清楚地评估优化效果（如"合并质量评估省了多少钱"）。

---

**文档生成时间**：2026-08-04

## 阶段 5 收口记录（2026-09-19）

当前主定位已收口为“无人机智能售后技术支持 Agent”。`backend/eval/dataset.json` 已重建为 34 题无人机售后集，覆盖产品参数/型号、故障排查、SOP、飞行安全、法规、闲聊、时效性、知识库缺口、跨机型陷阱、synthetic 案例、人工升级和多轮排查失败。题目只引用 `data/drone` 已存在的文档身份，结构化 gold 暂标 `inferred`，发布前需人工逐题复核。

评估脚本保留旧指标和兼容字段，新增 `intent_accuracy`、`product_model_accuracy`、`document_type_priority_accuracy`、`safety_recall`、`escalation_accuracy` 与 `cross_model_contamination_count`。缺少 API、GPU、联网服务或可靠 gold 时输出 `null`/未执行，不把离线结果包装成线上质量结论。

上线前仍有阻断项：生产密钥轮换、CORS/反向代理/TLS、日志脱敏审计、文件权限、SQLite/Chroma 备份恢复、监控告警和 GPU/资源压测。`manifest.json` 登记 70 篇、实际 71 篇的差异仍按授权保留。当前未实现上传、图片分析、人工工单和真实客服系统。

**基于文件**：
- README.md（架构描述）
- PROJECT_CONTEXT.md（历史上下文记录，当前仓库未保留）
- eval/reports/（4 份 v1.1 历史评估报告；当前 v1.2 报告需重新运行脚本生成）
- eval/dataset.json（评估集）
- app/graph/prompts.py（git log）
- data/agent.db（数据库结构）
