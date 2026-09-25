# backend/app/graph/tools.py
# 导入 Optional 类型标注，用于声明"可为空"的参数/返回值
from typing import Optional
# 导入 asyncio，用于把同步的检索等调用包装到线程池（避免阻塞事件循环）
import asyncio
# 导入 inspect，用于检查检索器 retrieve 方法签名（判断是否支持 top_k 参数）
import inspect
# 导入 logging，用于记录运行日志
import logging
# 从 langchain_openai 导入 ChatOpenAI，用于调用 DeepSeek（OpenAI 兼容接口）
from langchain_openai import ChatOpenAI
# 导入 langchain_core 消息类型：系统/用户/AI 消息
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
# 导入 RunnableConfig，用于携带流式/元数据配置
from langchain_core.runnables import RunnableConfig
# 导入 pydantic BaseModel，用于定义结构化输出 schema
from pydantic import BaseModel
# 导入 TavilyClient，用于联网搜索
from tavily import TavilyClient
# 导入 tenacity 重试相关：重试装饰器、次数、指数退避、指定异常
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_not_exception_type
# 导入 tiktoken，用于精确估算 token 数量
import tiktoken
# 导入全局配置
from app.config import settings
# 导入证据 id 生成函数
from app.models.evidence import evidence_id
# 从 prompts 导入评估类提示词
from app.graph.prompts import (
    IS_RELEVANT_PROMPT,           # 相关性判断提示词
    IS_RETRIEVAL_QUALITY_PROMPT,  # 检索质量评估提示词
    IS_COMBINED_QUALITY_PROMPT,   # 合并质量评估提示词
)

# 获取当前模块日志器
logger = logging.getLogger(__name__)


# 判定类提示词映射表：judge_type → 对应提示词模板
JUDGE_PROMPTS = {
    "is_relevant": IS_RELEVANT_PROMPT,                    # 相关性判断
    "is_retrieval_quality": IS_RETRIEVAL_QUALITY_PROMPT,  # 检索质量判断
    # P1-1: 幻觉检测 + 答案质量评估已合并到 combined_quality_check_node，
    # 不再走 evaluate()，相关 judge_type 废弃。
}

# P1-9: History token 预算上限（保守估算）
# DeepSeek 32K context，预留 system+retrieval+answer ~12K，history 上限 6000
HISTORY_MAX_TOKENS = 6000  # 历史消息 token 上限

# P1-10: ChatOpenAI 实例缓存，按 (model, temperature) 键复用
# 避免每次 call_llm 都重新创建实例（重复配置解析和连接池建立）
_llm_cache: dict[tuple[str, float], ChatOpenAI] = {}  # LLM 实例缓存

# P1-11: tiktoken 编码器单例（延迟加载）
_tiktoken_encoder = None  # 编码器缓存，None=未加载，False=加载失败


# 定义获取 LLM 实例的函数（带缓存）
def _get_llm(model: str, temperature: float) -> ChatOpenAI:
    """获取（必要时创建）ChatOpenAI 实例，按 (model, temperature) 缓存。"""
    key = (model, temperature)      # 构造缓存键
    if key not in _llm_cache:       # 若无缓存
        _llm_cache[key] = ChatOpenAI(   # 创建并缓存实例
            model=model,                # 模型名
            temperature=temperature,    # 温度
            api_key=settings.DEEPSEEK_API_KEY,    # DeepSeek API key
            base_url=settings.DEEPSEEK_BASE_URL,  # DeepSeek base url
        )
    return _llm_cache[key]          # 返回缓存实例


# 定义 token 估算函数
def _estimate_tokens(text: str) -> int:
    """估算 token 数（P1-11: 改用 tiktoken 精确计数）。

    用 cl100k_base 编码器（GPT-4 编码器，对 DeepSeek 有 <10% 偏差但远准于字符估算）。
    保留字符估算 fallback：tiktoken 加载失败时退回 len*2//3。
    """
    if not text:             # 空文本
        return 0             # 0 token
    global _tiktoken_encoder             # 声明使用全局编码器
    if _tiktoken_encoder is None:        # 尚未加载
        try:                             # 尝试加载
            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")  # 获取编码器
        except Exception:                # 加载失败
            _tiktoken_encoder = False    # 标记失败，避免重复尝试
    if _tiktoken_encoder:                # 编码器可用
        return len(_tiktoken_encoder.encode(text))  # 精确编码计数
    # fallback：粗略估算（中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token）
    return max(1, len(text) * 2 // 3)    # 字符数*2//3 估算


# 定义历史截断函数
def _truncate_history(history: list[dict], max_tokens: int = HISTORY_MAX_TOKENS) -> list[dict]:
    """按 token 预算从最新向前保留 history。

    保留最近的消息（语义相关性更高），超出预算时丢弃最早的消息。
    单条消息超长时也保留（避免完全丢失当前对话上下文）。
    """
    if not history:          # 无历史
        return []            # 空列表

    kept = []                # 保留的消息
    used = 0                 # 已用 token 数
    for msg in reversed(history):        # 从最新往前遍历
        content = msg.get("content", "") # 取消息内容
        cost = _estimate_tokens(content) # 估算该条 token
        if kept and used + cost > max_tokens:  # 已有保留且超出预算
            break                          # 停止（丢弃更早的）
        kept.append(msg)               # 保留当前消息
        used += cost                   # 累计 token
    # kept 是倒序，恢复为时间正序
    kept.reverse()                     # 反转回正序
    return kept                        # 返回截断后历史


# 定义单一判断的 schema（passed + reason）
class JudgeSchema(BaseModel):
    passed: bool   # 是否通过
    reason: str    # 原因


# 定义合并质量评估输出 schema
class CombinedQualitySchema(BaseModel):
    """P1-1: 合并质量评估的输出 schema（幻觉+质量一次调用）。"""
    has_hallucination: bool  # 是否有幻觉
    answer_quality_pass: bool  # 答案质量是否通过
    reason: str              # 原因


# 定义单个分解子问题的 schema
class SubQuerySchema(BaseModel):
    """Validated representation of one decomposed retrieval query."""

    sub_query: str  # 子问题文本


# 定义问题分解输出 schema
class DecomposeSchema(BaseModel):
    """P0-2: 问题分解的输出 schema（意图分类 + 多步推理判断）。

    阶段 2: 追加安全评估字段，全部带默认值——旧模型输出（或旧测试 fixture）
    不含这些字段时仍可正常解析，向后兼容。
    """
    is_chitchat: bool                  # 是否闲聊
    needs_decomposition: bool          # 是否需要分解
    reasoning_steps: list[SubQuerySchema]  # 子问题列表
    intent: str = "knowledge_gap"         # 阶段 3：售后意图
    product_model: str | None = None       # 用户明确提及的机型
    component: str | None = None           # 涉及部件
    fault_type: str | None = None          # 故障类型
    safety_flag: bool = False          # 是否命中高风险情形
    safety_level: str = "none"         # "high" / "none"
    safety_situation: str = "unknown"  # "in_flight" / "landed" / "charging" / "unknown"
    user_requests_human: bool = False  # 用户明确要求转人工


# 用 tenacity 装饰器配置重试：最多3次、指数退避、ValueError 不重试、抛出原异常
@retry(
    stop=stop_after_attempt(3),                     # 最多尝试3次
    wait=wait_exponential(multiplier=1, min=1, max=8),  # 指数退避等待
    retry=retry_if_not_exception_type(ValueError),  # 除 ValueError 外都重试
    reraise=True,                                   # 重试耗尽后抛出原异常
)
# 定义带重试的非流式 LLM 调用包装
async def _call_llm_with_retry(kwargs: dict) -> dict:
    """Retry non-streaming calls without replaying visible token chunks."""
    return await _call_llm_once(**kwargs)  # 转发到单次调用


# 定义统一 LLM 调用的外层入口
async def call_llm(
    system_prompt: str,            # 系统提示词
    user_input: str,               # 用户输入
    temperature: float = 0.3,      # 温度，默认0.3
    output_schema: Optional[type[BaseModel]] = None,  # 结构化输出 schema（可选）
    history: list[dict] = None,    # 历史消息（可选）
    model: str = "deepseek-chat",  # 模型名，默认 deepseek-chat
    stream: bool = False,          # 是否流式输出
    config: Optional[RunnableConfig] = None,  # 运行时配置（可选）
) -> dict:
    """Call the LLM with retries for request-style calls.

    Streaming calls deliberately execute once.  Retrying an async stream after
    it has yielded chunks causes LangGraph to forward the first attempt again,
    duplicating text in the client.  The API layer sends a canonical ``final``
    event so a transient stream failure still has a deterministic reconciliation
    path when a node provides a fallback answer.
    """
    kwargs = {                     # 组装调用参数 dict
        "system_prompt": system_prompt,      # 系统提示词
        "user_input": user_input,            # 用户输入
        "temperature": temperature,          # 温度
        "output_schema": output_schema,      # schema
        "history": history,                  # 历史
        "model": model,                      # 模型
        "stream": stream,                    # 流式标志
        "config": config,                    # 配置
    }
    if stream:                     # 流式调用
        return await _call_llm_once(**kwargs)  # 只执行一次（不重试）
    return await _call_llm_with_retry(kwargs)  # 非流式：带重试


# 定义单次 LLM 调用实现
async def _call_llm_once(
    system_prompt: str,            # 系统提示词
    user_input: str,               # 用户输入
    temperature: float = 0.3,      # 温度
    output_schema: Optional[type[BaseModel]] = None,  # schema
    history: list[dict] = None,    # 历史
    model: str = "deepseek-chat",  # 模型
    stream: bool = False,          # 流式
    config: Optional[RunnableConfig] = None,  # 配置
) -> dict:
    """统一 LLM 调用工具。

    非流式调用由 call_llm 外层执行 3 次指数退避重试；流式调用只执行一次，
    避免在已经下发部分 token 后从头重试造成重复文本。

    stream=True 时通过 llm.astream() 产生 token 级流式事件（on_chat_model_stream），
    被 LangGraph 的 astream_events(version="v2") 捕获并经 SSE 推送到前端。
    显式传递 config 确保 token 事件稳定传播（不依赖 contextvar 隐式行为）。

    注意：
    - 流式传输中途失败由节点级 fallback 和 API 层 final 事件处理；
      不会重放已下发 token。
    - output_schema（function_calling）与 streaming 有兼容性问题，仅在纯文本生成节点启用。
    - 节点函数需注入 config: RunnableConfig 参数（LangGraph 自动注入）并向下传递。
    """
    # P2-5: 从 config.metadata 提取 conversation_id 用于日志关联
    conv_id = None                 # 初始化会话 id
    if config is not None:         # 有配置
        metadata = config.get("metadata") or {}  # 取 metadata
        conv_id = metadata.get("conversation_id")  # 取会话 id
    conv_tag = f"conversation_id={conv_id} " if conv_id else ""  # 构造日志前缀

    logger.debug(                  # 记录调试日志
        f"{conv_tag}call_llm model={model} temp={temperature} "
        f"stream={stream} schema={'yes' if output_schema else 'no'}"
    )

    llm = _get_llm(model, temperature)  # 获取（缓存）LLM 实例

    messages = [SystemMessage(content=system_prompt)]  # 初始消息列表（含系统提示）
    if history:                    # 若有历史
        # P1-9: 按 token 预算截断 history，避免超出 context window
        truncated = _truncate_history(history)  # 截断历史
        for h in truncated:        # 遍历截断后历史
            if h["role"] == "user":              # 用户消息
                messages.append(HumanMessage(content=h["content"]))  # 转 HumanMessage
            else:                                # 否则视为 AI 消息
                messages.append(AIMessage(content=h["content"]))     # 转 AIMessage
    messages.append(HumanMessage(content=user_input))  # 追加当前用户输入

    if output_schema:              # 若需结构化输出
        # DeepSeek 不支持 response_format（JSON mode），必须用 function_calling 方式。
        # langchain_openai 新版默认可能用 json_schema，需显式指定 method。
        structured_llm = llm.with_structured_output(output_schema, method="function_calling")  # 包装
        result = await structured_llm.ainvoke(messages, config=config)  # 调用
        # Pydantic V2 模型转 dict
        if hasattr(result, "model_dump"):        # 若是 Pydantic V2 模型
            return {"text": "", "structured": result.model_dump()}  # 用 model_dump 转 dict
        return {"text": "", "structured": dict(result)}  # 否则直接转 dict

    if stream:                     # 流式模式
        # 流式模式：显式传 config，确保 on_chat_model_stream 事件
        # 经 RunnableConfig.callbacks 稳定传播到 astream_events。
        # 聚合 chunk 返回完整文本，后续节点（quality_gate）仍拿到完整答案。
        chunks = []                # 收集 token 块
        async for chunk in llm.astream(messages, config=config):  # 流式迭代
            content = getattr(chunk, "content", None) or ""  # 取块内容
            if content:            # 非空才收集
                chunks.append(content)  # 追加
        return {"text": "".join(chunks), "structured": None}  # 拼接返回完整文本

    response = await llm.ainvoke(messages, config=config)  # 非流式调用
    return {"text": response.content, "structured": None}  # 返回响应文本


# 定义统一评估工具函数
async def evaluate(judge_type: str, source: str, answer: str = "", query: str = "") -> dict:
    """统一评估工具。全部用 temp=0.2（修复温度不一致问题）。

    retry 已上移到 call_llm（3 次重试），此处不再重复 retry 避免嵌套。
    上层 quality_gate_node 仍做 try/except 降级兜底。
    ValueError（未知 judge_type）不重试，直接抛出。
    """
    if judge_type not in JUDGE_PROMPTS:  # 若 judge_type 未注册
        raise ValueError(f"Unknown judge_type: {judge_type}")  # 抛出（不重试）

    prompt = JUDGE_PROMPTS[judge_type].format(source=source, answer=answer, query=query)  # 填充提示词
    result = await call_llm(       # 调用 LLM
        system_prompt=prompt,      # 提示词
        user_input=query or "请评估",  # 用户输入
        temperature=0.2,           # 低温度
        output_schema=JudgeSchema, # 结构化 schema
        model=settings.MODEL_FLASH,  # 快速模型
    )
    return {                       # 返回评估结果
        "judge_type": judge_type,              # 判断类型
        "passed": result["structured"]["passed"],  # 是否通过
        "raw_output": result["structured"],    # 原始输出
    }


# 定义检索工具函数
async def retrieve(
    query: str,
    rag_retriever,
    top_k: int = 3,
    metadata_constraints: dict[str, str] | None = None,
    document_type_priority: list[str] | None = None,
) -> list[dict]:
    """调用 RAGRetriever（同步函数，用 asyncio.to_thread 包装）。"""
    # RAGRetriever exposes ``final_top_k`` and supports request-scoped top_k.
    # Keep a small compatibility path for third-party retrievers that still
    # implement the historical ``retrieve(query)`` signature.
    try:                                       # 尝试检查签名
        params = inspect.signature(rag_retriever.retrieve).parameters  # 取 retrieve 方法参数
        supports_top_k = "top_k" in params or any(   # 判断是否支持 top_k 或 **kwargs
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
    except (AttributeError, TypeError, ValueError):  # 签名检查失败
        supports_top_k = False                 # 视为不支持
    kwargs = {"top_k": top_k}
    if metadata_constraints:
        kwargs["metadata_constraints"] = metadata_constraints
    if document_type_priority:
        kwargs["document_type_priority"] = document_type_priority
    if supports_top_k:                         # 支持 top_k
        return await asyncio.to_thread(rag_retriever.retrieve, query, **kwargs)  # 带策略调用
    return await asyncio.to_thread(rag_retriever.retrieve, query)  # 兼容旧签名调用


# P1-10: TavilyClient 模块级缓存，避免每次调用创建新实例
_tavily_client: TavilyClient | None = None  # Tavily 客户端缓存


# 定义获取 Tavily 客户端函数
def _get_tavily_client() -> TavilyClient:
    """获取（必要时创建）TavilyClient 实例，模块级单例。"""
    global _tavily_client           # 声明全局
    if _tavily_client is None:      # 未创建
        _tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)  # 创建并缓存
    return _tavily_client           # 返回客户端


# 定义 Tavily 搜索函数
async def tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Tavily 搜索。

    返回统一的 Evidence 列表，保留网页标题和 URL，供回答和 API
    引用使用。失败时返回一个带 ``is_error`` 标记的结构化条目，避免
    把错误文本误当作搜索结果。
    """
    try:                                      # 尝试搜索
        client = _get_tavily_client()         # 获取客户端
        result_count = max(0, int(max_results))  # 归一化结果数量
        response = await asyncio.to_thread(   # 线程池执行同步搜索
            client.search, query=query, max_results=result_count, search_depth="basic"
        )
        results = response.get("results", []) or []  # 取结果列表
        evidence: list[dict] = []              # 初始化证据列表
        for result in results[:result_count]: # 遍历结果
            if not isinstance(result, dict):  # 跳过非字典项
                continue
            content = str(result.get("content") or "").strip()  # 取内容并去空白
            if not content:                   # 内容为空，跳过
                continue
            url = result.get("url")           # 取 URL
            title = str(result.get("title") or url or "联网搜索结果")  # 取标题
            evidence.append({                 # 构造证据项
                "id": f"web:{evidence_id(str(url or ''), title, content)}",  # 证据 id
                "source_type": "web",         # 来源类型=web
                "title": title,               # 标题
                "content": content,           # 内容
                "url": url,                   # URL
                "source": title,              # 来源=标题
                "document_id": None,          # 无文档 id
                "chunk_id": None,             # 无分块 id
                "score": None,                # 无得分
            })
        if not evidence:                      # 无可用证据
            return [{                         # 返回空结果错误占位
                "id": "web:empty",            # id
                "source_type": "web",         # 类型
                "title": "联网搜索未返回结果",   # 标题
                "content": "联网搜索未返回结果",  # 内容
                "url": None,                  # URL
                "source": "联网搜索未返回结果",  # 来源
                "document_id": None,          # 文档 id
                "chunk_id": None,             # 分块 id
                "score": None,                # 得分
                "is_error": True,             # 错误标记
            }]
        return evidence                       # 返回证据列表
    except Exception as e:                    # 搜索异常
        # 记录完整错误到日志，但不中断流程
        err_type = type(e).__name__           # 错误类型名
        logger.error(f"Tavily 搜索失败（{err_type}）: {e}。query={query!r}")  # 记录错误
        return [{                             # 返回错误占位证据
            "id": f"web:error:{err_type}",    # 错误 id
            "source_type": "web",             # 类型
            "title": "联网搜索失败",           # 标题
            "content": f"联网搜索失败：{err_type}。请检查网络代理或 Tavily API key 配置。",  # 错误内容
            "url": None,                      # URL
            "source": "联网搜索失败",          # 来源
            "document_id": None,              # 文档 id
            "chunk_id": None,                 # 分块 id
            "score": None,                    # 得分
            "is_error": True,                 # 错误标记
        }]
