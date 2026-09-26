# Agent 升级评估报告（阶段 7）

- 日期：2026-09-26
- 数据集：`eval/dataset.json` **v2.1-drone-agent**（47 题 = 34 题既有 + 13 题新增场景）
- 运行方式：**真实在线评估**（进程内 ASGI 启动完整后端：DeepSeek + 本地 bge embedding/reranker + Chroma drone_kb + SQLite 隔离临时库），开关 `AGENT_FOLLOWUP_ENABLED=true`、`AGENT_AUTO_TICKET_ENABLED=true`
- 报告文件：`backend/eval/reports/report_20260926_141228.json`
- 诚实声明：全部 gold 标签 `gold_status=inferred`（未人工复核）；本报告数字不构成生产质量承诺

## 1. 数据集规模与 gold 分布

| 项 | 数值 |
|---|---|
| 总题数 | 47（45 题单轮执行 + 2 题 `multi_turn` 跳过待人工多轮验证） |
| gold_action 分布 | answer 27 / followup 5 / create_ticket 4 / escalate 9 / 不作断言（知识冲突）2 |
| 类别 | 17 类（新增 insufficient_info、insufficient_info_second_turn、service_needed、knowledge_conflict） |

## 2. 新增 Agent 业务指标（本次升级目标）

| 指标 | 数值 | 分母 | 说明 |
|---|---|---|---|
| **action_accuracy** | **65.1%** | 43 | recommended_action 四值精确匹配 |
| **ticket_action_accuracy** | **86.7%** | 45 | 自动建单触发与 gold 精确匹配；**误报 0**（39 道 gold=False 全部未建单），4 道 service_needed 全部漏报 |
| **followup_gap_hit_rate** | **90.0%** | 5 | 追问轮缺口字段命中 gold 缺口的平均比例 |
| **diagnosis_coverage** | **100%** | 23 | local 路径题全部产出结构化诊断（含自动降级重试后成功） |
| **diagnosis_citation_validity** | **100%** | 23 | 诊断引用 evidence_id 100% 锚定到真实证据（程序校验生效，LLM 无法编造证据 id） |

安全相关验证（与预期设计一致）：
- 高风险题（6 道）`safety_recall` **100%**，全部走 escalate 且**无一自动建单**（"高风险首轮不自动建单"规则真实生效）。
- `cross_model_contamination_count` = **0**（机型硬过滤未被破坏）。
- 两道知识冲突题按设计不进 action 分母，实际输出均并列呈现多来源且引用可校验。

## 3. 既有指标（回归对比）

| 指标 | 本次真实值 | 说明 |
|---|---|---|
| route_accuracy | 68.9% | **首次无人机版真实基线**——改造前 34 题从未真实跑通过（评估脚本缺登录逻辑，本次修复；reports 里仅有旧 v1.1/99 题数据，不可比） |
| intent_accuracy | 84.4% | |
| product_model_accuracy | 100% | |
| document_type_priority_accuracy | 82.9% | |
| safety_recall | 100% | |
| escalation_accuracy | 80% | |
| citation_correctness | 91.3% | |
| hallucination_suspected | 10 条（rate 28.6%，分母 35 有布尔判定） | 其中 9 条在 online 路径（质量检查对 Tavily 摘要偏保守），1 条 local |

> **为什么没有"改造前后对比"数字**：无人机版评估集在改造前从未真实执行（阶段 1 审查已确认该事实），本次是第一份真实基线。任何"before 数字"都是不存在的，不编造。

## 4. 失败案例分析（45 题中 15 题 action 不符、14 题路由不符）

### 4.1 escalate 误报 6 道（保守方向偏差，安全上可接受但需迭代）

drone-001（参数题）/006/010/021/031 等 gold=answer 的题实际 escalate。主因：G0 低置信触发链——参数/原理题也进入 diagnose，证据（产品文档）与诊断提示词的排查口径不匹配导致 citations 为空 → 置信度强制归零 → "diagnosis_confidence_low" 触发 escalate。**方向是保守的（宁可升级不硬答），且未引起误建单**，但把"参数咨询"升级为人工属于体验损耗。改进方向：意图为 product_parameter/technical_principle 时跳过 G0 的 diagnosis 缺失触发（这些意图本无"诊断"概念），或对非排查意图使用独立的置信口径。

### 4.2 service_needed 漏报 4 道（能力缺口，明确的后续迭代点）

- drone-042/046/047 → 实际 followup：decompose 对"更换 GPS 模块后仍不定位"这类题判了信息不足（还想要故障细节），followup 守卫本身工作正常，但"问题里已含明确硬件事实"时应视为充分。
- drone-044/045 → 路由 online（"升级固件"/"自检报错"触发时效性词表或相关性判定失败）→ 无诊断 → answer。时效性词表把"升级固件"（操作行为）误判为"求证最新版本"，是既有词表的已知局限。
- drone-043 → escalate（"腐蚀"命中安全关键词保守链）。安全方向正确。

### 4.3 路由不符 14 道

9 道 local 题走了 online（judge_relevance 的 LLM 兜底与时效性词表在边界题上偏保守），4 道 local 题走了 followup（decompose 对信息充分性偏严格），1 道 multi-step 误判。这些属于既有路由策略的真实表现首次被测量，不是本次改造引入的回归（无 before 数字可比，但失败模式均与本次新增节点无关——追问/诊断/决策节点只在分流后起作用）。

### 4.4 followup 相关

- 5 道 insufficient_info 中 4 道正确触发 followup 且缺口命中 90%（"飞机总是往一边偏" drone-037 因命中漂移关键词被安全兜底判高风险 → escalate，符合"高风险永不追问"红线）。
- drone-026（"已排查两次仍无效"）期望 escalate 实际 followup：该题的升级信号（fault_progress 计数）依赖会话历史，单轮评估天然无法注入；同时暴露 decompose 未把"问题文本自述的排查历史"当作升级信号——已记录为提示词迭代点。

## 5. 已知局限

1. 全部 gold 为 `inferred`，未人工复核；action_accuracy 等指标存在 gold 本身偏差的可能。
2. 2 道 `insufficient_info_second_turn` 需要多轮会话验证，单轮评估器跳过（已标注，待脚本化多轮验证）。
3. 评估期间自动建单会写库——本次使用隔离临时库（`agent_eval_tmp.db`，跑完已删除），正式环境跑评估需注意。
4. 真实评估包含 LLM 随机性（temperature 0.2-0.7），单次运行数字有波动；未做多轮重复取均值。

## 6. 后续优化（按收益排序）

1. **非排查意图的决策口径**：product_parameter/technical_principle 意图跳过 diagnosis 缺失触发的 escalate（预期可把 action_accuracy 从 65% 提到 ~75%+）。
2. **decompose 充分性提示词迭代**：问题文本含"已排查 N 次""更换过部件"等硬件事实时不应判信息不足；自述排查历史应视作升级信号。
3. **时效性词表拆分**："升级固件"（操作）与"最新固件版本"（求证）分流。
4. **service_needed 场景回流**：4 道漏报题加入回归集，gold 复核后置 verified。
5. 引入真实用户问题回流（`from_query_log`），逐步替换 seed 题。
