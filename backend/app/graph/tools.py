from typing import Optional
import asyncio
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel
from tavily import TavilyClient
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_not_exception_type
import tiktoken
from app.config import settings
from app.graph.prompts import (
    IS_RELEVANT_PROMPT,
    IS_RETRIEVAL_QUALITY_PROMPT,
    IS_COMBINED_QUALITY_PROMPT,
)

logger = logging.getLogger(__name__)


JUDGE_PROMPTS = {
    "is_relevant": IS_RELEVANT_PROMPT,
    "is_retrieval_quality": IS_RETRIEVAL_QUALITY_PROMPT,
    # P1-1: 幻觉检测 + 答案质量评估已合并到 combined_quality_check_node，
    # 不再走 evaluate()，相关 judge_type 废弃。
}

# P1-9: History token 预算上限（保守估算）
# DeepSeek 32K context，预留 system+retrieval+answer ~12K，history 上限 6000
HISTORY_MAX_TOKENS = 6000

# P1-10: ChatOpenAI 实例缓存，按 (model, temperature) 键复用
# 避免每次 call_llm 都重新创建实例（重复配置解析和连接池建立）
_llm_cache: dict[tuple[str, float], ChatOpenAI] = {}

# P1-11: tiktoken 编码器单例（延迟加载）
_tiktoken_encoder = None


def _get_llm(model: str, temperature: float) -> ChatOpenAI:
    """获取（必要时创建）ChatOpenAI 实例，按 (model, temperature) 缓存。"""
    key = (model, temperature)
    if key not in _llm_cache:
        _llm_cache[key] = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
        )
    return _llm_cache[key]


def _estimate_tokens(text: str) -> int:
    """估算 token 数（P1-11: 改用 tiktoken 精确计数）。

    用 cl100k_base 编码器（GPT-4 编码器，对 DeepSeek 有 <10% 偏差但远准于字符估算）。
    保留字符估算 fallback：tiktoken 加载失败时退回 len*2//3。
    """
    if not text:
        return 0
    global _tiktoken_encoder
    if _tiktoken_encoder is None:
        try:
            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tiktoken_encoder = False  # 标记加载失败，避免重复尝试
    if _tiktoken_encoder:
        return len(_tiktoken_encoder.encode(text))
    # fallback：粗略估算（中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token）
    return max(1, len(text) * 2 // 3)


def _truncate_history(history: list[dict], max_tokens: int = HISTORY_MAX_TOKENS) -> list[dict]:
    """按 token 预算从最新向前保留 history。

    保留最近的消息（语义相关性更高），超出预算时丢弃最早的消息。
    单条消息超长时也保留（避免完全丢失当前对话上下文）。
    """
    if not history:
        return []

    kept = []
    used = 0
    for msg in reversed(history):
        content = msg.get("content", "")
        cost = _estimate_tokens(content)
        if kept and used + cost > max_tokens:
            break
        kept.append(msg)
        used += cost
    # kept 是倒序，恢复为时间正序
    kept.reverse()
    return kept


class JudgeSchema(BaseModel):
    passed: bool
    reason: str


class CombinedQualitySchema(BaseModel):
    """P1-1: 合并质量评估的输出 schema（幻觉+质量一次调用）。"""
    has_hallucination: bool
    answer_quality_pass: bool
    reason: str


class DecomposeSchema(BaseModel):
    """P0-2: 问题分解的输出 schema（意图分类 + 多步推理判断）。"""
    is_chitchat: bool
    needs_decomposition: bool
    reasoning_steps: list[dict]


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_not_exception_type(ValueError),
    reraise=True,
)
async def call_llm(
    system_prompt: str,
    user_input: str,
    temperature: float = 0.3,
    output_schema: Optional[type[BaseModel]] = None,
    history: list[dict] = None,
    model: str = "deepseek-chat",
    stream: bool = False,
    config: Optional[RunnableConfig] = None,
) -> dict:
    """统一 LLM 调用工具。

    retry 策略：3 次重试，指数退避 1-8 秒，ValueError 不重试。
    覆盖所有 LLM 调用（evaluate / generate_answer / rewrite_query 等），
    避免单次 API 抖动导致整个对话流中断。

    stream=True 时通过 llm.astream() 产生 token 级流式事件（on_chat_model_stream），
    被 LangGraph 的 astream_events(version="v2") 捕获并经 SSE 推送到前端。
    显式传递 config 确保 token 事件稳定传播（不依赖 contextvar 隐式行为）。

    注意：
    - astream 模式下 retry 仍有意义：连接建立阶段失败可重试；
      流传输中途失败重试会从头开始（前端可能收到部分重复 token，可接受）。
    - output_schema（function_calling）与 streaming 有兼容性问题，仅在纯文本生成节点启用。
    - 节点函数需注入 config: RunnableConfig 参数（LangGraph 自动注入）并向下传递。
    """
    # P2-5: 从 config.metadata 提取 conversation_id 用于日志关联
    conv_id = None
    if config is not None:
        metadata = config.get("metadata") or {}
        conv_id = metadata.get("conversation_id")
    conv_tag = f"conversation_id={conv_id} " if conv_id else ""

    logger.debug(
        f"{conv_tag}call_llm model={model} temp={temperature} "
        f"stream={stream} schema={'yes' if output_schema else 'no'}"
    )

    llm = _get_llm(model, temperature)

    messages = [SystemMessage(content=system_prompt)]
    if history:
        # P1-9: 按 token 预算截断 history，避免超出 context window
        truncated = _truncate_history(history)
        for h in truncated:
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
            else:
                messages.append(AIMessage(content=h["content"]))
    messages.append(HumanMessage(content=user_input))

    if output_schema:
        # DeepSeek 不支持 response_format（JSON mode），必须用 function_calling 方式。
        # langchain_openai 新版默认可能用 json_schema，需显式指定 method。
        structured_llm = llm.with_structured_output(output_schema, method="function_calling")
        result = await structured_llm.ainvoke(messages, config=config)
        # Pydantic V2 模型转 dict
        if hasattr(result, "model_dump"):
            return {"text": "", "structured": result.model_dump()}
        return {"text": "", "structured": dict(result)}

    if stream:
        # 流式模式：显式传 config，确保 on_chat_model_stream 事件
        # 经 RunnableConfig.callbacks 稳定传播到 astream_events。
        # 聚合 chunk 返回完整文本，后续节点（quality_gate）仍拿到完整答案。
        chunks = []
        async for chunk in llm.astream(messages, config=config):
            content = getattr(chunk, "content", None) or ""
            if content:
                chunks.append(content)
        return {"text": "".join(chunks), "structured": None}

    response = await llm.ainvoke(messages, config=config)
    return {"text": response.content, "structured": None}


async def evaluate(judge_type: str, source: str, answer: str = "", query: str = "") -> dict:
    """统一评估工具。全部用 temp=0.2（修复温度不一致问题）。

    retry 已上移到 call_llm（3 次重试），此处不再重复 retry 避免嵌套。
    上层 quality_gate_node 仍做 try/except 降级兜底。
    ValueError（未知 judge_type）不重试，直接抛出。
    """
    if judge_type not in JUDGE_PROMPTS:
        raise ValueError(f"Unknown judge_type: {judge_type}")

    prompt = JUDGE_PROMPTS[judge_type].format(source=source, answer=answer, query=query)
    result = await call_llm(
        system_prompt=prompt,
        user_input=query or "请评估",
        temperature=0.2,
        output_schema=JudgeSchema,
        model=settings.MODEL_FLASH,
    )
    return {
        "judge_type": judge_type,
        "passed": result["structured"]["passed"],
        "raw_output": result["structured"],
    }


async def retrieve(query: str, rag_retriever, top_k: int = 3) -> list[dict]:
    """调用 RAGRetriever（同步函数，用 asyncio.to_thread 包装）。"""
    return await asyncio.to_thread(rag_retriever.retrieve, query)


# P1-10: TavilyClient 模块级缓存，避免每次调用创建新实例
_tavily_client: TavilyClient | None = None


def _get_tavily_client() -> TavilyClient:
    """获取（必要时创建）TavilyClient 实例，模块级单例。"""
    global _tavily_client
    if _tavily_client is None:
        _tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
    return _tavily_client


async def tavily_search(query: str, max_results: int = 5) -> str:
    """Tavily 搜索。

    失败时不抛异常，返回提示字符串让流程继续：
    - generate_answer(online) 会基于此空结果生成"无法获取实时信息"的回答
    - 避免单点 API 失败导致整个对话流中断（用户收到"服务内部错误"）
    - 常见失败：网络代理拦截（TUN 模式）、API key 失效、境外 API 超时
    """
    try:
        client = _get_tavily_client()
        response = await asyncio.to_thread(
            client.search, query=query, max_results=max_results, search_depth="basic"
        )
        results = response.get("results", [])
        if not results:
            return "（联网搜索未返回结果）"
        return "\n\n".join([f"[{i+1}] {r.get('content', '')}" for i, r in enumerate(results)])
    except Exception as e:
        # 记录完整错误到日志，但不中断流程
        err_type = type(e).__name__
        logger.error(f"Tavily 搜索失败（{err_type}）: {e}。query={query!r}")
        return f"（联网搜索失败：{err_type}。请检查网络代理或 Tavily API key 配置。）"
