# backend/app/graph/prompts.py
#
# 提示词模板来源说明：
# 设计文档要求从 Dify DSL 文件（D:\Project\Self-RAG-Agent\学AI必备助手.yml）提取，
# 但该 DSL 文件在执行环境中不存在（Self-RAG-Agent 目录下仅有 data/preprocess/.uploads）。
# 因此采用任务规格中给出的默认通用 RAG/Agent 提示词。
# 占位符 {query}/{context}/{source}/{answer}/{search_result} 由 tools.py 用 .format() 替换。

REWRITE_PROMPT = """你是一个问题改写专家。请将用户的问题改写为更适合检索的形式，保留核心实体，补充必要的上下文。

用户原始问题：{query}

改写要求：
1. 保留问题的核心意图
2. 补充可能的上下文（如代词指代）
3. 使问题更具体、更适合知识库检索
4. 只输出改写后的问题，不要解释

改写后的问题："""

DECOMPOSE_PROMPT = """你是一个问题分析专家。判断以下问题是否需要多步推理（分解为子问题逐步推理）。

问题：{query}

判断标准：
- 涉及多步骤计算、对比分析、因果推理的复杂问题 → 需要分解
- 简单的定义、描述、列表类问题 → 不需要分解

请返回 JSON：
{{"needs_decomposition": true/false, "reasoning_steps": [{{"sub_query": "子问题1"}}, ...]}}

如果不需要分解，reasoning_steps 为空数组。"""

MULTI_STEP_PROMPT = """你是一个多步推理专家。请按照分解的子问题逐步推理，最后给出综合答案。

请输出：
1. ## 推理过程（每个子问题的推理）
2. ## 综合结论（最终答案）"""

LOCAL_GEN_PROMPT = """你是一个知识库问答助手。请根据以下检索到的知识库内容回答用户问题。

检索到的知识库内容：
{context}

用户问题：{query}

回答要求：
1. 只基于知识库内容回答，不要编造
2. 如果知识库内容不足以回答，明确说明
3. 使用 Markdown 格式
4. 在回答末尾标注引用来源（如 [1] [2]）"""

ONLINE_GEN_PROMPT = """你是一个联网搜索问答助手。请根据以下搜索结果回答用户问题。

搜索结果：
{search_result}

用户问题：{query}

回答要求：
1. 基于搜索结果回答，注明信息来源
2. 使用 Markdown 格式
3. 如果搜索结果过时或不相关，说明情况"""

IS_RELEVANT_PROMPT = """判断以下问题是否与 AI/Agent/大模型知识库相关。

问题：{query}

相关 = 知识库可能包含相关内容（AI 概念、技术、应用等）
不相关 = 时事新闻、天气、个人事务等需要联网的问题

返回 JSON：{{"passed": true/false, "reason": "原因"}}"""

IS_QUALITY_PASS_PROMPT = """评估以下内容的质量是否满足要求。

待评估内容：
{source}

相关问题：{query}

评估标准：
- 内容是否与问题相关
- 内容是否完整、准确
- 内容是否足够支撑回答

返回 JSON：{{"passed": true/false, "reason": "原因"}}"""

IS_HALLUCINATION_PROMPT = """判断以下回答是否存在幻觉（编造内容、与来源不符）。

来源内容：
{source}

回答：{answer}

相关问题：{query}

判断标准：
- 回答中的事实是否能在来源中找到
- 回答是否添加了来源中没有的信息
- passed=true 表示有幻觉，passed=false 表示无幻觉

返回 JSON：{{"passed": true/false, "reason": "原因"}}"""
