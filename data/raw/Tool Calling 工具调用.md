---
title: Tool Calling 工具调用
date: 2026-07-22
tags:
  - AI
  - LLM
  - Agent
  - function-calling
  - tool-use
aliases:
  - Function Calling
  - 函数调用
  - 工具调用
  - Tool Use
cssclasses:
  - knowledge-note
---

# Tool Calling 工具调用

## 一、定义

Tool Calling（工具调用，也称 Function Calling / Tool Use）是赋予大语言模型识别并请求调用外部工具的能力。开发者将工具定义（JSON Schema）传给 LLM，LLM 根据用户输入判断是否需要调用工具，若需要则输出结构化的调用指令（函数名 + 参数），由应用程序执行并将结果返回 LLM，最终生成自然语言回复。

> [!tip] 一句话
> Tool Calling 是给 LLM 这个"大脑"装上了"手"和"眼睛"——让它不再只是生成文本，而是能真正操作外部世界。

> [!note] 术语辨析
> **Function Calling** 是 OpenAI 2023 年 6 月首创的 API 能力，偏重"调用函数"；**Tool Calling** 是更广义的概念，工具可以是函数、数据库、搜索引擎、Agent、文件系统等任何外部实体。2026 年主流模型（GPT-4o、Claude 3.5、Gemini 2.5）已统一使用 Tool Calling 作为推荐术语。

## 二、为什么出现

**核心问题：LLM 是纯文本生成器，有三大先天缺陷，必须通过工具调用弥补。**

1. **无法获取实时信息**：LLM 的知识截止于训练日期，无法回答"今天股价多少"、"当前天气如何"等时效性问题。需要搜索引擎、天气 API 等工具。

2. **数学与逻辑推理短板**：LLM 基于概率预测下一个 token，做复杂算术时经常产生幻觉（Hallucination）。需要计算器、Python 解释器等工具。

3. **无法与外部世界交互**：LLM 只能生成文字，不能真正"做事"——发邮件、查数据库、调用 API、控制智能家居等。需要各种外部 API 和系统接口。

OpenAI 于 2023 年 6 月率先在 API 中引入 Function Calling 功能，此后 Anthropic（Tool Use，2024.03）、Google Gemini（Function Calling，2024.02）、DeepSeek、Qwen 等主流厂商纷纷跟进。到 2026 年，所有主流模型的工具调用能力已经趋同，但如何设计工具、编排工具、处理工具错误，仍然是拉开 Agent 质量差距的核心因素。

## 三、核心思想

**关键认知：LLM 永远不会自己执行代码。** 当触发 Tool Calling 时，LLM 只是生成了一段结构化的文本指令（JSON），真正的代码执行完全由应用程序完成。

核心原理拆解为三个层面：

1. **工具定义（Tool Definition）**：开发者用 JSON Schema 描述每个工具的功能、参数类型、参数描述和必填项。这是 LLM 理解工具的"说明书"。`name` 和 `description` 是最关键的字段——LLM 通过这些信息做语义匹配判断何时调用。

```json
{
  "name": "get_weather",
  "description": "获取指定城市的实时天气信息",
  "parameters": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string",
        "description": "城市名称，如 Beijing, Shanghai"
      }
    },
    "required": ["location"]
  }
}
```

2. **工具选择与参数提取**：LLM 根据用户输入和工具描述，自动判断三个问题：是否需要调用工具？调用哪个工具？提取什么参数？这是模型通过专门微调获得的"意图识别 + 槽位填充"能力。

3. **"LLM → 代码 → LLM" 三明治结构**：LLM 输出调用指令 → 应用代码执行工具 → 将执行结果注入对话上下文 → LLM 基于结果生成最终回复。整个过程是一个闭环。

> [!important] 本质
> Tool Calling 本质上解决的是"自然语言 → 机器指令"的翻译问题——将非结构化的用户意图，翻译为结构化的 API 调用。

## 四、工作流程

```mermaid
graph TD
    A[用户输入: 今天北京天气如何?] --> B[应用构建请求<br/>User Message + Tools Definition]
    B --> C[LLM 推理判断]
    C --> D{需要调用工具?}
    D -->|否| E[直接生成文本回复]
    D -->|是| F[LLM 输出 tool_calls<br/>name: get_weather<br/>args: {location: Beijing}]
    F --> G[应用解析 tool_calls]
    G --> H[执行本地函数<br/>调用天气 API]
    H --> I[获取返回结果<br/>24°C, 晴]
    I --> J[将 Tool Result 注入上下文<br/>role: tool, content: 结果]
    J --> K[再次调用 LLM<br/>User Message + Tool Call + Tool Result]
    K --> L[LLM 整合结果生成最终回复<br/>北京今天晴天，气温 24°C]
    
    E --> M[返回给用户]
    L --> M
    
    style C fill:#e1f5fe
    style F fill:#fff3e0
    style H fill:#e8f5e9
    style L fill:#fce4ec
```

**关键步骤详解**：

1. **应用发送请求**：将用户消息 + 工具定义列表（JSON Schema）一并发送给 LLM API
2. **LLM 返回 tool_calls**：若 LLM 决定调用工具，响应中 `content` 为 `null`，`tool_calls` 包含函数名和参数
3. **应用执行工具**：解析 `tool_calls`，调用对应的本地函数或远程 API，获取实际结果
4. **注入结果**：将工具执行结果以 `role: "tool"` 消息形式追加到对话历史中，并通过 `tool_call_id` 关联
5. **LLM 生成最终回复**：再次调用 LLM，LLM 根据工具结果生成自然语言回答

## 五、关键技术

### 5.1 各大厂商的 Tool Calling 实现

| 厂商 | 命名 | 引入时间 | 关键特性 |
|------|------|----------|----------|
| **OpenAI** | Function Calling / Tools | 2023.06 | 首创者，支持 `tool_choice`（auto/none/required/指定函数），Parallel Function Calling，Strict Mode JSON Schema |
| **Anthropic** | Tool Use | 2024.03 | 支持 `tool_choice`（auto/any/tool），Computer Use 操作桌面，与 MCP 深度集成 |
| **Google Gemini** | Function Calling | 2024.02 | 原生 SDK 可直接传入 Python 函数自动反射生成 Schema，支持 `FunctionCallingConfigMode`（AUTO/ANY/NONE） |
| **DeepSeek** | Function Calling | 2024 | 兼容 OpenAI API 格式，支持串联/并联/自动 Debug 三种推理模式 |
| **Qwen / 通义千问** | Function Calling | 2024 | 兼容 OpenAI 格式，中文场景效果优秀 |

### 5.2 tool_choice 控制策略

决定 LLM 选择工具行为的最重要参数：

- **`auto`（默认）**：模型自行判断是否需要调用工具，最灵活，适合通用助手
- **`none`**：禁止调用任何工具，只生成文本回复，适合纯知识问答、翻译、摘要
- **`required` / `any`**：强制调用工具，适合路由 Agent 第一步、强制查询数据库等场景
- **指定函数名**：强制调用特定工具，适合工作流固定步骤（如 `{"type": "function", "function": {"name": "get_weather"}}`）

### 5.3 Parallel Function Calling（并行工具调用）

OpenAI 2023 年 11 月推出的关键能力。LLM 在一次响应中同时请求调用多个相互独立的工具，而非串行逐个调用。例如用户问"北京和上海的天气分别如何？"，模型同时返回两个 `get_weather` 调用，大幅降低延迟。条件是工具之间必须相互独立，不能有数据依赖。

### 5.4 Structured Output（结构化输出）

2024 年 OpenAI 推出的能力，与 Function Calling 互补：

- **Function Calling**：LLM 输出 JSON 格式的调用指令（函数名 + 参数），用于"调用工具"
- **Structured Output**：LLM 输出符合指定 JSON Schema 的结构化数据，用于需要模型直接输出可解析 JSON 的场景

两者共同基础是 **JSON Schema 约束**，通过 `strict: true` 模式确保 100% 符合 Schema。2026 年的共识是：格式层用 JSON Schema / Structured Output / Function Calling 约束，业务层用校验、规则、重试兜底，不要指望一个 Prompt 同时解决这两件事。

### 5.5 ReAct 模式 vs Native Function Calling

| 维度 | ReAct（Prompt 工程） | Native Function Calling |
|------|---------------------|------------------------|
| 实现方式 | 在 System Prompt 手写工具格式，代码解析模型输出的文本 | 通过 API 原生 `tools` 参数传递 JSON Schema |
| 稳定性 | 低，模型经常忘记格式，输出少个括号就解析失败 | 高，模型专门微调，100% 输出合法 JSON |
| Token 消耗 | 高，大量 Prompt 描述占用上下文 | 低，工具定义在 API 层面处理 |
| 灵活性 | 高，任何模型都可用 | 需模型厂商支持 |
| 典型场景 | 早期/不支持 Function Calling 的模型 | 现代主流模型，生产环境首选 |

**结论**：2026 年能用 Native Function Calling 就不要用 ReAct，除非模型不支持。在 LangChain 中对应 `create_tool_calling_agent`（Native）和 `create_react_agent`（ReAct），前者利用模型原生能力更稳定，后者在 Prompt 中显式定义推理过程更透明。

### 5.6 工具定义最佳实践

1. **函数命名**：用描述性名称，如 `search_knowledge_base` 而非 `search`
2. **描述质量**：`description` 是 LLM 理解何时调用工具的最关键信息来源，应清晰说明用途、适用场景和限制
3. **参数设计**：合理使用 `required`，只标记真正必要的参数；`enum` 约束可选值范围
4. **参数描述**：每个参数都应有 `description`，举例说明合法值（如 `e.g. "Beijing", "Shanghai"`）
5. **工具粒度**：每个工具职责单一，避免 `update_user_and_send_email` 这种"大杂烩"
6. **安全约束入描述**：在 `description` 中写明"只用于查询，不可用于修改或删除"

## 六、优点

1. **突破 LLM 固有局限**：让 LLM 获取实时数据、执行精确计算、操作外部系统，弥补知识截止、数学短板和无法交互三大缺陷

2. **结构化输出保证可靠性**：Native Function Calling 通过模型微调确保 100% 输出合法 JSON，比 ReAct 的文本解析方案稳定得多

3. **并行调用减少延迟**：Parallel Function Calling 允许一次请求同时调用多个独立工具，避免串行等待

4. **灵活的工具选择策略**：`tool_choice` 参数支持 auto/required/none/指定函数四种模式，适配不同场景

5. **跨厂商兼容性趋好**：OpenAI 的 Function Calling 格式已成为事实标准，DeepSeek、Qwen、Mistral 等纷纷兼容

6. **Agent 的核心基石**：没有 Tool Calling 的 Agent 只能是聊天机器人，有了它才能实现感知-决策-执行闭环

7. **安全可控**：LLM 只生成调用指令，实际执行由开发者控制，可在代码层做权限校验、参数验证、速率限制

## 七、缺点

1. **厂商格式不统一**：Anthropic（Tool Use）、Google Gemini（FunctionDeclaration）与 OpenAI 格式仍有差异，跨厂商切换需要适配层

2. **模型理解工具的准确性有限**：当工具列表超过 20 个或功能相似时，LLM 容易选错工具或提取错误参数

3. **额外延迟**：每次 Tool Calling 至少 2 次 LLM API 调用（判断 + 生成结果），复杂 Agent 可能涉及 5-10 轮调用

4. **Token 消耗增加**：工具定义、工具调用结果均占用上下文窗口，多轮调用后上下文迅速膨胀

5. **安全风险（Prompt Injection）**：恶意用户可能通过 Prompt 注入诱导 LLM 调用不该调用的工具，如果工具不加权限控制后果严重

6. **错误处理复杂**：工具执行失败时需设计降级和重试机制，LLM 自身无法处理这些异常

7. **调试困难**：涉及 LLM 推理 + 代码执行的多层交互，难以定位是模型选错工具、参数提取有误还是工具执行出错

8. **Small 模型效果差**：小参数模型（<7B）的 Function Calling 能力普遍较弱，建议使用 7B 以上且经过专门微调的模型

## 八、典型应用

1. **AI Agent（智能体）**：Tool Calling 是 Agent 的核心能力。Agent 通过工具调用实现感知-决策-执行的闭环，如 AutoGPT、CrewAI、LangChain Agent 等

2. **智能客服系统**：查询订单 → 调用 `query_order(order_id)`；申请退款 → 调用 `create_refund(order_id, reason)`；全部通过 Tool Calling 实现

3. **知识库问答（RAG + Tool Calling）**：检索器封装为 Tool，LLM 按需调用 `search_knowledge_base`、`query_database`、`run_sql` 等，实现 Agentic RAG

4. **数据分析助手**：用户用自然语言描述分析需求 → LLM 调用 `python_repl` 或 `run_sql` 执行代码 → 返回分析结果

5. **个人助理/日程管理**：调用 `create_calendar_event`、`send_email`、`search_web`、`get_weather` 等工具完成多步骤任务

6. **电商推荐与搜索**：用户"帮我找 200 元以内评分最高的蓝牙耳机" → LLM 调用 `search_products` 筛选商品 → 返回推荐

7. **代码助手（Cursor/Copilot）**：LLM 调用 `read_file`、`search_codebase`、`run_terminal` 等工具直接操作代码库和开发环境

8. **MCP 应用**：MCP Server 暴露工具，MCP Client（LLM）调用工具，实现 AI 应用的"即插即用"

## 九、面试高频问题

### Q1：Function Calling 和 Tool Calling 有什么区别？

- **Function Calling**：狭义上指 OpenAI 2023 年 6 月引入的 API 能力，LLM 输出 JSON 格式的函数调用指令，偏重"调用本地函数/API"
- **Tool Calling**：更广义的概念，工具可以是函数、数据库、搜索引擎、Agent、文件系统等任何外部实体。Anthropic 官方使用 "Tool Use" 一词

**结论**：Function Calling 是实现 Tool Calling 最常见的技术手段。在 2026 年的现代模型中，Tool Calling 已成为更推荐的广义术语。

### Q2：ReAct 模式和 Native Function Calling 的核心区别是什么？

**ReAct**：通过 Prompt 工程教 LLM 按特定格式输出（如 `Action: search, Action Input: query`），代码解析文本。不稳定但灵活，适用不支持 Function Calling 的模型。

**Native Function Calling**：通过 API 的 `tools` 参数传递 JSON Schema，模型专门微调过，输出合法 JSON。稳定但依赖厂商支持。

**核心区别**：ReAct 是"用自然语言约定协议"，Function Calling 是"用结构化数据定义协议"。2026 年能用 Native Function Calling 就不要用 ReAct。

### Q3：LLM 是如何"知道"该调用哪个工具的？

LLM 通过语义匹配 + 槽位填充 + 微调训练做工具选择。模型将用户输入与每个工具的 `name` 和 `description` 做语义匹配，判断哪个工具最相关，再从输入中提取参数值。`description` 是最关键的信息源——写得越好，LLM 越能准确判断。

### Q4：Parallel Function Calling 是什么？有什么条件？

LLM 在一次响应中同时请求调用多个相互独立的工具，应用端并行执行。条件：工具之间必须相互独立，不能有数据依赖。如果 Tool B 需要 Tool A 的输出作为输入，仍需串行调用。支持模型：GPT-4/4o、DeepSeek、Gemini 等主流模型。

### Q5：tool_choice 的 auto/none/required 分别适用于什么场景？

- **`auto`**：通用助手，用户可能问知识性问题也可能需要工具，最灵活
- **`none`**：纯知识问答、情感分析、文本摘要、翻译，不需要外部交互
- **`required`**：路由 Agent 第一步、强制查询数据库，确保模型不会"偷懒"直接生成文本
- **指定函数名**：工作流固定步骤，如"用户输入必须先用 spell_check 做拼写检查"

### Q6：Tool Calling 的安全风险有哪些？如何防范？

**风险**：Prompt Injection 诱导调用危险工具、参数注入（如 SQL 注入）、过度授权。

**防范**：最小权限原则（不暴露危险工具）、参数校验（类型/范围/白名单）、用户确认机制（高风险操作二次确认）、工具描述中加入安全约束、速率限制。

### Q7：工具调用失败时，如何处理？

标准流程：捕获异常并区分网络错误/参数错误/业务错误 → 返回结构化错误信息（含 `retryable` 字段）→ 注入错误上下文让 LLM 决定下一步 → 可重试错误设置 2-3 次重试 → 不可恢复错误向用户诚实说明。不要只返回 "Error" 字符串。

### Q8：如何测试和评估 Tool Calling 的准确性？

三个核心指标：工具选择准确率（Tool Selection Accuracy）、参数提取准确率（Argument Extraction Accuracy）、端到端成功率（End-to-End Success Rate）。测试方法：单元测试（Mock 工具函数验证 tool_calls 结构）、集成测试（真实调用工具验证完整链路）、回归测试（维护典型用例测试集）。评估框架：LangSmith、Weights & Biases。

## 十、相关知识

- [[Agent|AI Agent]] — Tool Calling 是 Agent 的核心能力，Agent 通过工具调用实现感知-决策-执行闭环
- [[MCP 模型上下文协议|MCP 模型上下文协议]] — MCP 是 Tool Calling 的标准化协议，定义工具如何被分发和调用
- [[LangChain-LangGraph|LangChain 与 LangGraph]] — LangChain 的 `bind_tools`、`create_tool_calling_agent` 封装了 Tool Calling 的完整流程
- [[RAG 检索增强生成|RAG]] — RAG 检索器可封装为 Tool，让 LLM 按需调用，实现 Agentic RAG
- [[LLM 大语言模型|LLM 大语言模型]] — Tool Calling 是 LLM 的核心扩展能力，需要模型专门微调支持
- [[Prompt Engineering 提示词工程|Prompt Engineering]] — ReAct 模式是 Tool Calling 的 Prompt Engineering 实现，Native Function Calling 是其进化版
- [[Loop Engineering 循环工程|Loop Engineering]] — Tool Calling 是 Loop 中 Plan-Execute-Evaluate 循环中 Execute 环节的关键
- [[Harness Engineering 驾驭工程|Harness Engineering]] — 驾驭工程管理 Tool Calling 的工具定义、调用、执行全生命周期
- [[Embedding 向量嵌入|Embedding 向量嵌入]] — Tool Calling 可让 LLM 按需调用 Embedding 工具做语义搜索
- Structured Output（结构化输出） — 与 Tool Calling 互补，确保 LLM 输出符合 JSON Schema
- JSON Schema — Tool Calling 中工具定义的事实标准格式
- ReAct（Reasoning + Acting） — Tool Calling 的 Prompt Engineering 实现方式
- Parallel Function Calling — 并行调用多个独立工具，降低 Agent 延迟

## 十一、代码示例

### 示例 1：OpenAI Native Function Calling

```python
from openai import OpenAI
import json

client = OpenAI(api_key="your-api-key")

# 定义工具（JSON Schema）
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的实时天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "城市名称，如 Beijing, Shanghai"
                    }
                },
                "required": ["location"]
            }
        }
    }
]

# 模拟天气查询函数
def get_weather(location: str) -> str:
    weather_data = {"Beijing": "晴天，24°C", "Shanghai": "多云，28°C"}
    return weather_data.get(location, "未知城市")

# 发送请求
messages = [{"role": "user", "content": "今天北京天气怎么样？"}]

response = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    tools=tools,
    tool_choice="auto"
)

# 检查是否触发了工具调用
assistant_message = response.choices[0].message
if assistant_message.tool_calls:
    tool_call = assistant_message.tool_calls[0]
    function_name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments)
    print(f"LLM 请求调用: {function_name}({arguments})")
    
    # 执行工具
    if function_name == "get_weather":
        result = get_weather(arguments["location"])
    
    # 将工具结果注入上下文
    messages.append(assistant_message)
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": result
    })
    
    # 再次调用 LLM 生成最终回复
    final_response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )
    print(f"最终回复: {final_response.choices[0].message.content}")
else:
    print(f"直接回复: {assistant_message.content}")
```

### 示例 2：LangChain bind_tools 方式（推荐）

```python
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, ToolMessage

# 使用 @tool 装饰器定义工具（自动生成 JSON Schema）
@tool
def get_weather(location: str) -> str:
    """获取指定城市的实时天气信息。
    
    Args:
        location: 城市名称，如 Beijing, Shanghai
    """
    weather_data = {"Beijing": "晴天，24°C", "Shanghai": "多云，28°C"}
    return weather_data.get(location, "未知城市")

@tool
def calculate(expression: str) -> str:
    """执行数学计算。
    
    Args:
        expression: 数学表达式，如 '123 * 456'
    """
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"计算错误: {e}"

# 初始化模型并绑定工具
model = init_chat_model(model="gpt-4o", model_provider="openai")
llm_with_tools = model.bind_tools([get_weather, calculate])

# 执行
messages = [HumanMessage(content="北京今天天气如何？另外帮我算一下 456 * 789")]
response = llm_with_tools.invoke(messages)

# 处理工具调用
for tool_call in response.tool_calls:
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    print(f"调用工具: {tool_name}({tool_args})")
    
    if tool_name == "get_weather":
        result = get_weather.invoke(tool_args)
    elif tool_name == "calculate":
        result = calculate.invoke(tool_args)
    
    messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

# 生成最终回复
final_response = model.invoke(messages)
print(f"最终回复: {final_response.content}")
```

### 示例 3：LangGraph Agent 自动执行（Tool Calling Agent）

```python
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

# 定义工具
@tool
def search_knowledge_base(query: str) -> str:
    """搜索企业内部知识库。
    
    Args:
        query: 搜索关键词或问题
    """
    kb = {
        "年假": "员工每年享有 10 天带薪年假，工作满 1 年即可申请",
        "报销": "差旅报销需在 30 天内提交，通过 OA 系统审批",
    }
    for key, value in kb.items():
        if key in query:
            return value
    return "未找到相关信息"

@tool
def query_database(sql: str) -> str:
    """执行 SQL 查询（只读）。
    
    Args:
        sql: SELECT 查询语句
    """
    if not sql.strip().upper().startswith("SELECT"):
        return "错误：只允许执行 SELECT 查询"
    return '[{"name": "张三", "department": "技术部", "leave_days": 8}]'

# 创建 Agent（自动处理 Tool Calling 循环）
model = init_chat_model(model="gpt-4o", model_provider="openai")
tools = [search_knowledge_base, query_database]
agent = create_react_agent(model, tools)

# 执行
response = agent.invoke({
    "messages": [("user", "我有多少天年假？技术部张三还剩多少天？")]
})

for msg in response["messages"]:
    if hasattr(msg, "content") and msg.content:
        print(f"[{msg.type.upper()}]: {msg.content[:200]}")
```

### 示例 4：Parallel Function Calling（并行调用）

```python
from openai import OpenAI
import json
import concurrent.futures

client = OpenAI(api_key="your-api-key")

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的实时天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市名称"}
                },
                "required": ["location"]
            }
        }
    }
]

def get_weather(location: str) -> str:
    data = {"北京": "晴天 24°C", "上海": "多云 28°C", "广州": "阵雨 30°C"}
    return data.get(location, "未知")

# 用户同时询问多个城市 → LLM 并行调用
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "北京、上海、广州今天天气分别怎么样？"}],
    tools=tools
)

message = response.choices[0].message
if message.tool_calls:
    print(f"并行调用 {len(message.tool_calls)} 个工具:")
    
    def execute_tool(tc):
        args = json.loads(tc.function.arguments)
        return {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": get_weather(args["location"])
        }
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        tool_messages = list(executor.map(execute_tool, message.tool_calls))
    
    for tm in tool_messages:
        print(f"  {tm['tool_call_id']}: {tm['content']}")
    
    final_response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": "北京、上海、广州今天天气分别怎么样？"},
            message,
            *tool_messages
        ]
    )
    print(f"\n汇总回复: {final_response.choices[0].message.content}")
```

### 示例 5：安全防护——工具调用权限校验

```python
from functools import wraps
from typing import Callable

def require_permission(permission: str):
    """工具调用权限校验装饰器"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_permissions = get_current_user_permissions()
            if permission not in user_permissions:
                return f"权限不足：需要 {permission} 权限"
            return func(*args, **kwargs)
        return wrapper
    return decorator

def get_current_user_permissions() -> list[str]:
    # 实际项目中从 JWT / Session 获取
    return ["read", "query"]

@tool
@require_permission("read")
def search_documents(query: str) -> str:
    """搜索文档（需要 read 权限）"""
    return f"搜索结果: 关于 '{query}' 的 3 篇文档"

@tool
@require_permission("admin")
def delete_document(doc_id: str) -> str:
    """删除文档（需要 admin 权限）"""
    return f"文档 {doc_id} 已删除"

# 参数白名单校验
def safe_query_database(sql: str) -> str:
    """安全的数据库查询"""
    if not sql.strip().upper().startswith("SELECT"):
        return "错误：只允许 SELECT 查询"
    forbidden_tables = ["users", "passwords", "secrets"]
    sql_upper = sql.upper()
    for table in forbidden_tables:
        if table.upper() in sql_upper:
            return f"错误：禁止查询 {table} 表"
    return f"查询结果: [{sql}] 返回 5 行数据"
```

## 十二、个人理解

**Tool Calling 是 LLM 从"聊天玩具"到"生产力工具"的分水岭。** 没有 Tool Calling 的 LLM 是知识渊博但手脚被绑住的"图书馆管理员"——能回答，但不能做事。有了 Tool Calling，LLM 才真正具备了操作现实世界的能力。这也是 2025-2026 年 Agent 大爆发的底层技术原因。

**Function Calling vs Tool Calling 的术语之争，本质上是行业对"工具"概念认知的升级。** 2023 年大家认为 LLM 只需要"调用函数"，后来发现可以扩展到操作数据库、搜索网页、控制浏览器、甚至操作计算机桌面（Anthropic Computer Use）。工具的概念从"函数"扩展到了"任何外部能力"。MCP 就是试图将 Tool Calling 标准化为类似 USB 协议的"即插即用"标准。

**Tool Calling 的核心挑战不是"能不能调用"，而是"能不能调用对"。** 工具列表 3-5 个时准确率很高（>95%），但 20-50 个且功能重叠时准确率显著下降。解决思路：工具分组按领域路由、工具描述精确语义区分、RAG 辅助工具选择。2026 年所有主流模型工具调用能力已趋同，但工具设计、编排、错误处理仍是拉开 Agent 质量差距的核心因素。

**安全是 Tool Calling 最容易被忽视但最致命的问题。** 太多开发者直接把 `sudo rm -rf /` 级别的工具暴露给 LLM 且不加权限校验。Prompt Injection 在 Tool Calling 场景下尤其危险——攻击者只需"说服"LLM 调用危险工具。**永远不要相信 LLM 会"自觉"不调用危险工具，安全必须由代码层强制执行。**

**选型建议**：生产环境优先使用 LangChain/LangGraph 的 Agent 框架，它封装了 Tool Calling 的完整生命周期。多工具场景建议用 `create_tool_calling_agent`（Native Function Calling 更稳定）而非 `create_react_agent`（ReAct 模式更透明但更脆弱）。如果使用 Anthropic 或 Google Gemini，注意格式差异，LangChain 的 `bind_tools` 可以帮你做适配。