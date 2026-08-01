# backend/app/api/chat.py
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import ChatRequest
from app.services.conversation_store import ConversationStore
from app.api.errors import ERROR_MESSAGES
from app.main import get_store
from app.extensions import limiter

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


STAGE_LABELS = {
    "rewrite_query": "正在理解问题...",
    "decompose_question": "正在分析问题类型...",
    "chitchat_node": "正在回应...",
    "judge_relevance": "正在判断问题类型...",
    "rag_retrieve": "正在检索知识库...",
    "rag_quality_eval": "正在评估检索质量...",
    "query_corrector": "正在优化检索词...",
    "web_search": "正在联网搜索...",
    "generate_local": "正在生成回答...",
    "generate_online": "正在生成回答...",
    "multi_step_reason": "正在逐步推理...",
    "combined_quality_check": "正在评估答案质量...",
    "quality_fail": "正在生成提示...",
}


@router.post("")
@limiter.limit("10/minute")
async def chat_stream(
    request: Request,
    body: ChatRequest,
    store: ConversationStore = Depends(get_store),
):
    # 先校验会话存在（404），再调用 get_graph()，避免 graph 未初始化时返回 500
    conv = await store.get_conversation(body.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    graph = get_graph()  # 直接调用，便于测试 monkeypatch

    await store.add_message(
        body.conversation_id, role="user", content=body.message
    )
    history = await store.get_history(body.conversation_id, limit=10)

    input_state = {
        "query": body.message,
        "conversation_id": body.conversation_id,
        "history": history[:-1],  # 排除刚加入的 user 消息
        "judge_log": [],
    }

    async def event_generator():
        final_state = None
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
                    stage_text = STAGE_LABELS.get(node_name, f"执行: {node_name}")
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "stage", "data": stage_text}),
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
                elif event["event"] == "on_chain_end" and event["name"] == "LangGraph":
                    final_state = event["data"]["output"]

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

    return EventSourceResponse(event_generator())
