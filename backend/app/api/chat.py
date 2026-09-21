# backend/app/api/chat.py
import asyncio
import json
import logging
import time
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import ChatRequest
from app.models.query_log import QueryLogCreate
from app.services.conversation_store import ConversationStore
from app.services.query_log_service import QueryLogStore
from app.api.errors import ERROR_MESSAGES
from app.main import get_store, get_query_log_store
from app.config import settings
from app.extensions import limiter
from app.api.dependencies import get_current_user
from app.api.trace import (
    extract_reasoning_content,
    extract_trace_output,
    stage_label,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger(__name__)

_graph = None


def set_graph(graph) -> None:
    global _graph
    _graph = graph


def get_graph():
    if _graph is None:
        raise RuntimeError("Graph not initialized")
    return _graph


def _infer_models_used(route_path: str) -> dict:
    """根据 route_path 推断各节点使用的模型（本轮非真实采集，P2 阶段填充真实数据）。

    依据 config.py 的 MODEL_FLASH / MODEL_PRO_CHAT / MODEL_PRO_REASON 映射：
    - chitchat/local/online → MODEL_PRO_CHAT
    - decomposition → MODEL_PRO_REASON
    - 所有路径的 rewrite_query/decompose/quality_eval 用 MODEL_FLASH
    """
    gen_model = settings.MODEL_PRO_REASON if route_path == "decomposition" else settings.MODEL_PRO_CHAT
    return {
        "rewrite_query": settings.MODEL_FLASH,
        "decompose_question": settings.MODEL_FLASH,
        "generation": gen_model,
        "quality_eval": settings.MODEL_FLASH,
    }


@router.post("")
@limiter.limit("10/minute")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    store: ConversationStore = Depends(get_store),
    user=Depends(get_current_user),
):
    # 第 1 阶段：记录请求起始时间与 log_id（即使异常也要落库）
    t0 = time.time()
    log_id = str(uuid4())

    # 先校验会话存在（404），再调用 get_graph()，避免 graph 未初始化时返回 500
    conv = await store.get_conversation(body.conversation_id, user.id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    graph = get_graph()  # 直接调用，便于测试 monkeypatch

    await store.add_message(
        body.conversation_id, role="user", content=body.message
    )
    history = await store.get_history(body.conversation_id, limit=10, user_id=user.id)

    input_state = {
        "query": body.message,
        "conversation_id": body.conversation_id,
        "history": history[:-1],  # 排除刚加入的 user 消息
        "judge_log": [],
    }

    async def event_generator():
        final_state = None
        error_msg = None  # 异常时填充，finally 落库用
        node_start_times: dict[str, float] = {}  # 节点执行开始时间（计算 duration_ms）
        try:
            # P2-5: 通过 config.metadata 传递 conversation_id，
            # 让 call_llm 等下游节点能在日志中关联会话
            runnable_config = {
                "metadata": {"conversation_id": body.conversation_id}
            }
            async for event in graph.astream_events(
                input_state, version="v2", config=runnable_config
            ):
                if event["event"] == "on_chain_start":
                    node_name = event["name"]
                    if node_name == "LangGraph":
                        continue  # 总图入口不发 stage
                    node_start_times[node_name] = time.time()
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "stage",
                                "data": {
                                    "node": node_name,
                                    "label": stage_label(node_name),
                                },
                            }
                        ),
                    }
                elif event["event"] in ("on_chat_model_stream", "on_llm_stream"):
                    # on_chat_model_stream: ChatOpenAI 等 BaseChatModel 的流式事件
                    # on_llm_stream: BaseLLM（非 chat）的流式事件（兼容保留）
                    chunk = event["data"]["chunk"]
                    # chunk 可能是对象（含 .content 属性）或 dict（含 "content" 键）
                    if hasattr(chunk, "content"):
                        content = chunk.content
                    elif isinstance(chunk, dict):
                        content = chunk.get("content", "")
                    else:
                        content = ""
                    if content:
                        yield {
                            "event": "message",
                            "data": json.dumps({"type": "token", "data": content}),
                        }
                    # deepseek-reasoner 思维链增量（其余模型为空串，静默跳过）
                    reasoning = extract_reasoning_content(chunk)
                    if reasoning:
                        yield {
                            "event": "message",
                            "data": json.dumps(
                                {"type": "reasoning", "data": reasoning}
                            ),
                        }
                elif event["event"] == "on_chain_end":
                    if event["name"] == "LangGraph":
                        final_state = event["data"]["output"]
                        continue
                    node_name = event["name"]
                    duration_ms = int(
                        (time.time() - node_start_times.get(node_name, time.time()))
                        * 1000
                    )
                    yield {
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "node_end",
                                "data": {
                                    "node": node_name,
                                    "label": stage_label(node_name),
                                    "duration_ms": duration_ms,
                                    "output": extract_trace_output(
                                        node_name, event["data"].get("output")
                                    ),
                                },
                            }
                        ),
                    }

            if final_state:
                route_path = final_state.get("route_path")
                # sources 按 route_path 取对应来源，避免 online 路径错误展示 RAG 检索结果。
                # - local/decomposition: 用 retrieval_result（可能为空，decomposition 无检索）
                # - online: 不返回 sources（web_search_result 是纯文本，无结构化来源）
                #   前端 AssistantMessage 已在无 sources 时清理 [1][2] 引用标记
                if route_path == "online":
                    sources_for_meta = []
                else:
                    sources_for_meta = final_state.get("retrieval_result", [])

                await store.add_message(
                    body.conversation_id,
                    role="assistant",
                    content=final_state.get("final_answer", ""),
                    route_path=route_path,
                    sources=sources_for_meta,
                    judge_log=final_state.get("judge_log", []),
                )
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {
                            "type": "meta",
                            "data": {
                                "route_path": route_path,
                                "sources": sources_for_meta,
                                "judge_log": final_state.get("judge_log", []),
                                # P1-3: 质量警告（仅 quality_fail 路径有值）
                                "quality_warning": final_state.get("quality_warning"),
                                # 第 2 阶段：query_log_id 供前端绑定反馈
                                "query_log_id": log_id,
                            },
                        }
                    ),
                }
            yield {"event": "message", "data": json.dumps({"type": "done"})}
        except Exception as e:
            # P1-11: 统一用 logger.exception() 记录（含 traceback），由 main.py 的
            # RotatingFileHandler 写入 app.log，不再手动写 errors.log
            err_type = type(e).__name__
            err_msg = str(e)
            error_msg = f"{err_type}: {err_msg}"
            logger.exception(
                f"对话流式失败 conversation_id={body.conversation_id} message={body.message!r}"
            )

            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "error",
                        "data": {
                            # 前端展示：优先用映射文案，未映射时附带异常类型帮助定位
                            "message": ERROR_MESSAGES.get(
                                err_type, f"服务内部错误（{err_type}: {err_msg[:100]}）"
                            )
                        },
                    }
                ),
            }
            yield {"event": "message", "data": json.dumps({"type": "done"})}
        finally:
            # 统一落库（成功/失败/客户端断开都写一条）
            # 关键：客户端在 done 后立即断开会触发 CancelledError（BaseException 子类，
            # 不被 except Exception 捕获），导致 await _write_query_log 被取消而无法落库。
            # 用 asyncio.shield 保护内部协程不被取消，并显式捕获 CancelledError。
            try:
                await asyncio.shield(_write_query_log(
                    log_id=log_id,
                    t0=t0,
                    body=body,
                    final_state=final_state,
                    error_msg=error_msg,
                    user_id=user.id,
                ))
            except asyncio.CancelledError:
                # shield 内部的 _write_query_log 会在后台继续执行完成；
                # 此处只记录日志，不 re-raise（响应已 yield 完毕，无需向上抛取消信号）
                logger.info(
                    f"客户端断开，query_log 后台写入中 log_id={log_id} conv={body.conversation_id}"
                )
            except Exception as log_err:
                logger.warning(
                    f"query_log 写入失败 log_id={log_id} conv={body.conversation_id}: {log_err}"
                )

    return EventSourceResponse(event_generator())


async def _write_query_log(
    log_id: str,
    t0: float,
    body: ChatRequest,
    final_state: dict | None,
    error_msg: str | None,
    user_id: str,
) -> None:
    """从 final_state 提取所有字段，一次性 INSERT 到 query_log 表。

    调用方在 finally 中调用，并已对异常做兜底；本函数内部不再 try/except。
    final_state 为 None 时（异常或客户端断开），关键字段写 NULL。
    """
    query_log_store = get_query_log_store()
    if query_log_store is None:
        # 测试环境可能未初始化，跳过落库
        return

    # 从 final_state 提取字段（None 时全填 None/默认值）
    if final_state:
        rewritten_query = final_state.get("rewritten_query")
        route_path = final_state.get("route_path")
        rewrite_count = final_state.get("correction_count", 0) or 0
        retrieval_result = final_state.get("retrieval_result", []) or []
        retrieved_doc_ids = json.dumps(
            [r.get("source") for r in retrieval_result], ensure_ascii=False
        )
        avg_reranker_score = final_state.get("avg_reranker_score")
        judge_log = final_state.get("judge_log", []) or []
        final_answer = final_state.get("final_answer")
        answer_length = len(final_answer) if final_answer else 0
        has_source = 1 if final_answer and "[来源：" in final_answer else 0
        models_used_json = json.dumps(
            _infer_models_used(route_path or ""), ensure_ascii=False
        )
    else:
        rewritten_query = None
        route_path = None
        rewrite_count = 0
        retrieved_doc_ids = None
        avg_reranker_score = None
        judge_log = []
        final_answer = None
        answer_length = 0
        has_source = 0
        models_used_json = None

    record = QueryLogCreate(
        id=log_id,
        conversation_id=body.conversation_id,
        user_id=user_id,
        user_label=body.user_label,
        raw_query=body.message,
        rewritten_query=rewritten_query,
        route_path=route_path,
        rewrite_count=rewrite_count,
        retrieved_doc_ids=retrieved_doc_ids,
        avg_reranker_score=avg_reranker_score,
        judge_log_json=json.dumps(judge_log, ensure_ascii=False),
        final_answer=final_answer,
        answer_length=answer_length,
        has_source=has_source,
        models_used_json=models_used_json,
        token_usage_json=None,  # 本轮预留，P2 阶段填充
        latency_ms=int((time.time() - t0) * 1000),
        error=error_msg,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await query_log_store.insert(record)
