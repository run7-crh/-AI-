# backend/app/api/chat.py
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import ChatRequest
from app.services.conversation_store import ConversationStore
from app.api.errors import ERROR_MESSAGES
from app.main import get_store

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
    "decompose_question": "正在分析问题结构...",
    "multi_step_reason": "正在进行多步推理...",
    "judge_relevance": "正在判断问题类型...",
    "rag_retrieve": "正在检索知识库...",
    "web_search": "正在联网搜索...",
    "generate_answer": "正在生成回答...",
    "quality_gate": "正在评估答案质量...",
    "fallback_online": "正在尝试联网搜索...",
}


@router.post("")
async def chat_stream(
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
            async for event in graph.astream_events(input_state, version="v2"):
                if event["event"] == "on_chain_start":
                    node_name = event["name"]
                    stage_text = STAGE_LABELS.get(node_name, f"执行: {node_name}")
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "stage", "data": stage_text}),
                    }
                elif event["event"] == "on_llm_stream":
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
                await store.add_message(
                    body.conversation_id,
                    role="assistant",
                    content=final_state.get("final_answer", ""),
                    route_path=final_state.get("route_path"),
                    sources=final_state.get("retrieval_result"),
                    judge_log=final_state.get("judge_log", []),
                )
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {
                            "type": "meta",
                            "data": {
                                "route_path": final_state.get("route_path"),
                                "sources": final_state.get("retrieval_result", []),
                                "judge_log": final_state.get("judge_log", []),
                            },
                        }
                    ),
                }
            yield {"event": "message", "data": json.dumps({"type": "done"})}
        except Exception as e:
            logger.exception("对话流式失败")
            yield {
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "error",
                        "data": {
                            "message": ERROR_MESSAGES.get(
                                type(e).__name__, "服务内部错误"
                            )
                        },
                    }
                ),
            }
            yield {"event": "message", "data": json.dumps({"type": "done"})}

    return EventSourceResponse(event_generator())
