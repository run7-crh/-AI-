# backend/app/api/chat.py
# 导入 asyncio，用于 shield 保护后台写入协程
import asyncio
# 导入 json，用于序列化 SSE 事件
import json
# 导入日志模块
import logging
# 导入 time，用于耗时统计
import time
# 导入 uuid4，用于生成本次请求的日志 id
from uuid import uuid4
# 导入 datetime 与 timezone，用于生成 UTC 时间戳
from datetime import datetime, timezone
# 导入 FastAPI 路由、依赖注入、异常、请求类
from fastapi import APIRouter, Depends, HTTPException, Request
# 导入 SSE 响应类，用于流式返回
from sse_starlette.sse import EventSourceResponse

# 导入聊天请求模型
from app.models.schemas import ChatRequest
# 导入查询日志写入模型
from app.models.query_log import QueryLogCreate
# 导入会话存储服务
from app.services.conversation_store import ConversationStore
# 导入查询日志存储服务
from app.services.query_log_service import QueryLogStore
from app.services.attachment_security import AttachmentValidationError
# 导入错误码文案映射
from app.api.errors import ERROR_MESSAGES
# 导入会话/查询日志/排查计数存储获取函数
from app.main import get_store, get_query_log_store, get_fault_progress_store, get_attachment_store
# 导入全局配置
from app.config import settings
# 导入全局限速器
from app.extensions import limiter
from app.api.dependencies import get_current_user
# 导入 trace 工具函数
from app.api.trace import (
    extract_reasoning_content,  # 提取推理链增量
    extract_trace_output,       # 按白名单提取节点 output
    stage_label,                # 节点名转中文标签
)

# 创建聊天路由，前缀 /api/chat
router = APIRouter(prefix="/api/chat", tags=["chat"])
# 获取当前模块日志器
logger = logging.getLogger(__name__)

_graph = None                     # 全局工作流图实例（由 main 注入）


# 过滤出可用证据
def _usable_evidence(items) -> list[dict]:
    """Return serialisable evidence that can be shown or logged as a source."""
    if not isinstance(items, list):        # 非列表
        return []
    return [                               # 过滤出可用证据
        item                               # 每条证据
        for item in items
        if isinstance(item, dict)          # 必须是字典
        and not item.get("is_error")       # 且非错误占位
        and isinstance(item.get("content"), str)  # content 是字符串
        and item["content"].strip()        # 且内容非空
    ]


def _public_attachment_evidence(items: list[dict]) -> list[dict]:
    """Expose bounded attachment previews while keeping full text transient."""
    public = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        copy = dict(item)
        content = str(copy.get("content", ""))
        # Keep source-card metadata useful without persisting or streaming the
        # extracted attachment body through messages/query_log.
        copy["content"] = "附件正文仅用于当前轮，未持久化"
        copy["content_truncated"] = bool(content)
        public.append(copy)
    return _usable_evidence(public)


# 依据最终路由选取要暴露的证据
def _sources_for_state(final_state: dict) -> list[dict]:
    """Select the final route's evidence for API, persistence and feedback."""
    route_path = final_state.get("route_path")     # 最终路由
    attachment_sources = _public_attachment_evidence(final_state.get("attachment_evidence", []))
    if route_path == "online":                     # 联网路径
        return _usable_evidence(final_state.get("web_search_result", [])) + attachment_sources
    local_sources = _usable_evidence(final_state.get("retrieval_result", []))  # 本地证据
    if route_path != "decomposition":              # 非多步推理（普通本地路径）
        return local_sources + attachment_sources
    # Older multi-step states kept Web fallback only in web_search_result.
    # Merge it for API/log compatibility while deduplicating evidence already
    # copied into retrieval_result by the current node.
    merged = list(local_sources)                   # 先纳入本地证据
    seen = {                                       # 记录已见证据键
        item.get("id") or item.get("url") or item.get("content", "")[:120]
        for item in merged
    }
    for item in _usable_evidence(final_state.get("web_search_result", [])):  # 遍历联网证据
        key = item.get("id") or item.get("url") or item.get("content", "")[:120]  # 计算去重键
        if key not in seen:                        # 该证据未合并过
            merged.append(item)                    # 追加合并
            seen.add(key)                          # 记录键
    return merged + attachment_sources             # 返回合并后的证据


# 从最终证据派生故障标识（机型__故障类型），用于排查失败计数的可持久化归属
def _derive_fault_key(final_state: dict) -> str | None:
    """优先取 troubleshooting/case 证据的 product_model + fault_type 组合。

    生成不出来（无故障类证据或元数据缺失）时返回 None，不参与计数。
    """
    for item in _sources_for_state(final_state):        # 遍历最终暴露的证据
        if not isinstance(item, dict):                  # 非字典跳过
            continue
        if item.get("document_type") not in ("troubleshooting", "case"):  # 仅故障类文档
            continue
        product_model = str(item.get("product_model") or "").strip()   # 机型
        fault_type = str(item.get("fault_type") or "").strip()         # 故障类型
        component = str(item.get("component") or "").strip()           # 部件兜底
        fault = fault_type or component                                 # 故障类型优先
        if not fault:                                    # 无故障信息
            continue                                     # 看下一条
        return f"{product_model or 'unknown'}__{fault}"  # 归一化故障标识
    return None                                          # 无故障类证据


# 注入工作流图实例
def set_graph(graph) -> None:
    global _graph
    _graph = graph                 # 保存图实例


# 获取当前工作流图实例
def get_graph():
    if _graph is None:             # 尚未初始化
        raise RuntimeError("Graph not initialized")  # 抛错
    return _graph                  # 返回图实例


# 按路由推断使用的模型
def _infer_models_used(route_path: str) -> dict:
    """根据 route_path 推断各节点使用的模型（本轮非真实采集，P2 阶段填充真实数据）。

    依据 config.py 的 MODEL_FLASH / MODEL_PRO_CHAT / MODEL_PRO_REASON 映射：
    - chitchat/local/online → MODEL_PRO_CHAT
    - decomposition → MODEL_PRO_REASON
    - 所有路径的 rewrite_query/decompose/quality_eval 用 MODEL_FLASH
    """
    gen_model = settings.MODEL_PRO_REASON if route_path == "decomposition" else settings.MODEL_PRO_CHAT  # 生成模型按路径选择
    return {                                          # 返回各节点模型映射
        "rewrite_query": settings.MODEL_FLASH,        # 意图改写用 flash
        "decompose_question": settings.MODEL_FLASH,   # 分解用 flash
        "generation": gen_model,                      # 生成用推断值
        "quality_eval": settings.MODEL_FLASH,         # 质量评估用 flash
    }


# 定义聊天流式接口
@router.post("")
@limiter.limit("10/minute")          # 每分钟限 10 次
async def chat_stream(
    request: Request,
    body: ChatRequest,
    store: ConversationStore = Depends(get_store),
    user=Depends(get_current_user),
):
    # 第 1 阶段：记录请求起始时间与 log_id（即使异常也要落库）
    t0 = time.time()                 # 请求起始时间
    log_id = str(uuid4())            # 生成本次请求日志 id

    # 先校验会话存在（404），再调用 get_graph()，避免 graph 未初始化时返回 500
    conv = await store.get_conversation(body.conversation_id, user.id)  # 查会话
    if not conv:                     # 会话不存在
        raise HTTPException(status_code=404, detail="会话不存在")  # 404
    graph = get_graph()              # 直接调用，便于测试 monkeypatch

    attachment_ids = list(body.attachment_ids or [])
    attachment_bundle = {"attachment_context": "", "attachment_evidence": [], "attachment_parse_status": "none"}
    if attachment_ids:
        attachment_store = get_attachment_store()
        if attachment_store is None:
            raise HTTPException(status_code=503, detail="附件服务未初始化")
        try:
            attachment_bundle = await attachment_store.prepare_chat_attachments(
                body.conversation_id, attachment_ids
            )
        except AttachmentValidationError as exc:
            raise HTTPException(status_code=400, detail=exc.code)

    user_message_id = await store.add_message(         # 存储用户消息
        body.conversation_id, role="user", content=body.message
    )
    for attachment_id in attachment_ids:
        if not await attachment_store.link_message_attachment(
            body.conversation_id, user_message_id, attachment_id
        ):
            raise HTTPException(status_code=400, detail="attachment_not_ready")
    history_full = await store.get_history(body.conversation_id, limit=10, user_id=user.id)  # 取最近 10 条历史
    # 阶段 3: 追问守卫——上一条 assistant 回答是否为追问轮（route_path=="followup"）。
    # get_history 额外返回 route_path；LLM 历史只消费 role/content，构造输入前剥离。
    last_assistant = next(
        (m for m in reversed(history_full) if m.get("role") == "assistant"), None
    )
    followup_just_asked = bool(
        last_assistant and last_assistant.get("route_path") == "followup"
    )
    history = [
        {"role": m.get("role"), "content": m.get("content")}
        for m in history_full
    ]

    # 阶段 2: 排查失败计数——用户"确认执行且仍无效"时对上一轮故障累加，
    # 并检查是否存在达到阈值的故障，为图注入 prior_troubleshoot_failed
    fault_progress = get_fault_progress_store()       # 排查计数存储（可能 None）
    query_log_store_for_progress = get_query_log_store()  # 日志存储（可能 None）
    prior_troubleshoot_failed = False                 # 默认未触发
    if fault_progress is not None:                    # 计数服务可用
        try:                                          # 计数失败不阻塞对话
            await fault_progress.record_confirmation( # 累加确认无效信号
                query_log_store_for_progress, body.conversation_id, body.message
            )
            prior_troubleshoot_failed = await fault_progress.has_repeated_failure(  # 阈值检查
                body.conversation_id
            )
        except Exception as progress_err:             # 计数异常降级
            logger.warning(f"排查失败计数异常（忽略）: {progress_err}")

    input_state = {                  # 构造工作流输入状态
        "query": body.message,       # 用户问题
        "conversation_id": body.conversation_id,  # 会话 id
        "history": history[:-1],     # 排除刚加入的 user 消息
        "judge_log": [],             # 空的判断日志数组
        "prior_troubleshoot_failed": prior_troubleshoot_failed,  # 阶段 2: 两次排查无效标记
        "followup_just_asked": followup_just_asked,  # 阶段 3: 上一轮刚追问过（最多连续追问 1 轮）
        "attachment_ids": attachment_ids,
        "attachment_context": attachment_bundle.get("attachment_context", ""),
        "attachment_evidence": attachment_bundle.get("attachment_evidence", []),
        "attachment_parse_status": attachment_bundle.get("attachment_parse_status", "none"),
    }

    # 定义 SSE 事件生成器
    async def event_generator():
        final_state = None           # 工作流最终状态
        error_msg = None             # 异常时填充，finally 落库用
        log_written = False          # 查询日志是否已写入
        node_start_times: dict[str, float] = {}  # 节点执行开始时间（计算 duration_ms）
        try:                         # 尝试流式执行
            if attachment_ids:
                # Optional event understood by new clients; old SSE clients
                # ignore unknown payload types and continue with stage/token.
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "attachment",
                        "data": {
                            "phase": "parse",
                            "status": "ready",
                            "attachment_ids": attachment_ids,
                            "count": len(attachment_ids),
                            "extracted_chars": attachment_bundle.get("total_chars", 0),
                            "message": "附件已解析并准备作为本轮临时资料",
                        },
                    }, ensure_ascii=False),
                }
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "attachment",
                        "data": {
                            "phase": "context",
                            "status": "ready",
                            "attachment_ids": attachment_ids,
                            "count": len(attachment_ids),
                            "message": "附件仅作为本轮临时上下文使用",
                        },
                    }, ensure_ascii=False),
                }
            # P2-5: 通过 config.metadata 传递 conversation_id，
            # 让 call_llm 等下游节点能在日志中关联会话
            runnable_config = {      # 工作流运行配置
                "metadata": {"conversation_id": body.conversation_id}  # 注入会话 id 元数据
            }
            async for event in graph.astream_events(   # 异步遍历图事件流
                input_state, version="v2", config=runnable_config
            ):
                if event["event"] == "on_chain_start":  # 节点开始事件
                    node_name = event["name"]          # 节点名
                    if node_name == "LangGraph":       # 总图入口
                        continue  # 总图入口不发 stage
                    node_start_times[node_name] = time.time()  # 记录节点开始时间
                    if attachment_ids and node_name in {"rag_retrieve", "web_search"}:
                        yield {
                            "event": "message",
                            "data": json.dumps({
                                "type": "attachment",
                                "data": {
                                    "phase": "retrieve",
                                    "status": "started",
                                    "attachment_ids": attachment_ids,
                                    "message": "正在结合附件与售后知识库检索",
                                },
                            }, ensure_ascii=False),
                        }
                    yield {                            # 下发 stage 事件
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "stage",      # 事件类型：阶段
                                "data": {
                                    "node": node_name,      # 节点名
                                    "label": stage_label(node_name),  # 中文标签
                                },
                            }
                        ),
                    }
                elif event["event"] in ("on_chat_model_stream", "on_llm_stream"):  # 模型流式事件
                    # on_chat_model_stream: ChatOpenAI 等 BaseChatModel 的流式事件
                    # on_llm_stream: BaseLLM（非 chat）的流式事件（兼容保留）
                    chunk = event["data"]["chunk"]     # 取出流式片段
                    # chunk 可能是对象（含 .content 属性）或 dict（含 "content" 键）
                    if hasattr(chunk, "content"):      # 对象形态
                        content = chunk.content        # 取内容属性
                    elif isinstance(chunk, dict):      # 字典形态
                        content = chunk.get("content", "")  # 取 content 键
                    else:                              # 其它
                        content = ""                   # 空内容
                    if content:                        # 有文本增量
                        yield {                        # 下发 token 事件
                            "event": "message",
                            "data": json.dumps({"type": "token", "data": content}),
                        }
                    # deepseek-reasoner 思维链增量（其余模型为空串，静默跳过）
                    reasoning = extract_reasoning_content(chunk)  # 提取推理链增量
                    if reasoning:                      # 有推理内容
                        yield {                        # 下发 reasoning 事件
                            "event": "message",
                            "data": json.dumps(
                                {"type": "reasoning", "data": reasoning}
                            ),
                        }
                elif event["event"] == "on_chain_end": # 节点结束事件
                    if event["name"] == "LangGraph":   # 总图结束
                        final_state = event["data"]["output"]  # 记录最终状态
                        continue                       # 不单独发节点事件
                    node_name = event["name"]          # 节点名
                    duration_ms = int(                 # 计算节点耗时毫秒
                        (time.time() - node_start_times.get(node_name, time.time()))  # 结束减开始
                        * 1000
                    )
                    yield {                            # 下发 node_end 事件
                        "event": "message",
                        "data": json.dumps(
                            {
                                "type": "node_end",   # 事件类型：节点结束
                                "data": {
                                    "node": node_name,      # 节点名
                                    "label": stage_label(node_name),  # 中文标签
                                    "duration_ms": duration_ms,  # 耗时
                                    "output": extract_trace_output(  # 白名单提取 output
                                        node_name, event["data"].get("output")
                                    ),
                                },
                            }
                        ),
                    }

            if final_state:                            # 工作流正常结束
                route_path = final_state.get("route_path")  # 最终路由
                sources_for_meta = _sources_for_state(final_state)  # 选取可用证据
                # Persist the diagnostic row before exposing query_log_id to the
                # client.  Otherwise a fast feedback click can race the
                # finally-block insert and receive a spurious 404.
                query_log_persisted = False            # 标记日志是否完成写入
                try:                                   # 尝试写入日志
                    query_log_persisted = await _write_query_log(  # 频繁路径写入日志
                        log_id=log_id,                 # 日志 id
                        t0=t0,                         # 起始时间
                        body=body,                     # 请求体
                        final_state=final_state,       # 最终状态
                        error_msg=error_msg,           # 错误信息
                        user_id=user.id,
                    )
                    log_written = query_log_persisted  # 同步写入标记
                except Exception as log_err:           # 写入失败
                    logger.warning(                    # 记录告警
                        f"query_log 写入失败 log_id={log_id} conv={body.conversation_id}: {log_err}"
                    )

                await store.add_message(               # 存储助手消息
                    body.conversation_id,              # 会话 id
                    role="assistant",                  # 助手角色
                    content=final_state.get("final_answer", ""),  # 回答内容
                    route_path=route_path,             # 路由路径
                    sources=sources_for_meta,          # 来源证据
                    judge_log=final_state.get("judge_log", []),  # 判断日志
                    quality_warning=final_state.get("quality_warning"),  # 质量告警
                    query_log_id=log_id if query_log_persisted else None,  # 关联日志 id
                    safety_flag=final_state.get("safety_flag"),
                    safety_level=final_state.get("safety_level"),
                    safety_situation=final_state.get("safety_situation"),
                    escalation_required=final_state.get("escalation_required"),
                    intent=final_state.get("intent"),
                    metadata_constraints=final_state.get("metadata_constraints"),
                    document_type_priority=final_state.get("document_type_priority"),
                )

                # Always send the canonical answer once.  Normal generation
                # also streams tokens, while fallback nodes may produce only a
                # final_state value; the client reconciles this event to avoid
                # blank or duplicated answers after retries.
                final_answer = final_state.get("final_answer")  # 最终回答
                if final_answer:                       # 有回答
                    yield {                            # 下发 final 事件
                        "event": "message",
                        "data": json.dumps(
                            {"type": "final", "data": final_answer},  # 最终回答内容
                            ensure_ascii=False,        # 保留非 ASCII 字符
                        ),
                    }
                yield {                                # 下发 meta 事件
                    "event": "message",
                    "data": json.dumps(
                        {
                            "type": "meta",            # 事件类型：元数据
                            "data": {
                                "route_path": route_path,         # 路由路径
                                "final_answer": final_answer,     # 最终回答
                                "sources": sources_for_meta,      # 来源证据
                                "judge_log": final_state.get("judge_log", []),  # 判断日志
                                # P1-3: 质量警告（仅 quality_fail 路径有值）
                                "quality_warning": final_state.get("quality_warning"),  # 质量告警
                                # 第 2 阶段：query_log_id 供前端绑定反馈
                                "query_log_id": log_id if query_log_persisted else None,  # 日志 id
                                # 阶段 2: 安全拦截与人工升级（可选新增字段，旧前端忽略）
                                "safety_flag": final_state.get("safety_flag"),           # 高风险命中
                                "safety_level": final_state.get("safety_level"),         # 安全等级
                                "safety_situation": final_state.get("safety_situation"), # 设备状态
                                "escalation_required": final_state.get("escalation_required"),  # 建议转人工
                                # 阶段 3：意图与检索元数据（仅透传后端已有状态）
                                "intent": final_state.get("intent"),
                                "metadata_constraints": final_state.get("metadata_constraints"),
                                "document_type_priority": final_state.get("document_type_priority"),
                                # 阶段 3：信息充分性与业务决策（可选新增字段，旧前端忽略）
                                "recommended_action": final_state.get("recommended_action"),
                                "information_gaps": final_state.get("information_gaps"),
                                "attachment_ids": attachment_ids or None,
                                "attachment_parse_status": final_state.get("attachment_parse_status", attachment_bundle.get("attachment_parse_status", "none")),
                            },
                        }
                    )
                }
            yield {"event": "message", "data": json.dumps({"type": "done"})}  # 下发完成事件
        except Exception as e:                         # 处理异常
            # P1-11: 统一用 logger.exception() 记录（含 traceback），由 main.py 的
            # RotatingFileHandler 写入 app.log，不再手动写 errors.log
            err_type = type(e).__name__                # 异常类型名
            err_msg = str(e)                           # 异常信息
            error_msg = f"{err_type}: {err_msg}"       # 组合错误描述
            logger.exception(                          # 记录异常堆栈
                f"对话流式失败 conversation_id={body.conversation_id} message={body.message!r}"
            )

            if attachment_ids:
                yield {
                    "event": "message",
                    "data": json.dumps({
                        "type": "attachment",
                        "data": {
                            "phase": "failed",
                            "status": "failed",
                            "attachment_ids": attachment_ids,
                            "error_code": "attachment_context_failed",
                            "message": "附件上下文未能完成处理",
                        },
                    }, ensure_ascii=False),
                }
            yield {                                    # 下发 error 事件
                "event": "message",
                "data": json.dumps(
                    {
                        "type": "error",               # 事件类型：错误
                        "data": {
                            # 前端展示：优先用映射文案，未映射时附带异常类型帮助定位
                            "message": ERROR_MESSAGES.get(  # 取映射文案
                                err_type, f"服务内部错误（{err_type}: {err_msg[:100]}）"  # 兜底文案
                            )
                        },
                    }
                ),
            }
            yield {"event": "message", "data": json.dumps({"type": "done"})}  # 下发完成
        finally:                                       # 收尾兜底
            # 统一落库（成功/失败/客户端断开都写一条）
            # 关键：客户端在 done 后立即断开会触发 CancelledError（BaseException 子类，
            # 不被 except Exception 捕获），导致 await _write_query_log 被取消而无法落库。
            # 用 asyncio.shield 保护内部协程不被取消，并显式捕获 CancelledError。
            try:                                       # 尝试兜底写入
                if not log_written:                    # 尚未写入
                    await asyncio.shield(_write_query_log(  # 受保护写入（不可被取消）
                        log_id=log_id,                 # 日志 id
                        t0=t0,                         # 起始时间
                        body=body,                     # 请求体
                        final_state=final_state,       # 最终状态
                        error_msg=error_msg,           # 错误信息
                        user_id=user.id,
                    ))
            except asyncio.CancelledError:             # 客户端断开触发的取消
                # shield 内部的 _write_query_log 会在后台继续执行完成；
                # 此处只记录日志，不 re-raise（响应已 yield 完毕，无需向上抛取消信号）
                logger.info(                           # 记录后台写入信息
                    f"客户端断开，query_log 后台写入中 log_id={log_id} conv={body.conversation_id}"
                )
            except Exception as log_err:               # 其它写入异常
                logger.warning(                        # 记录告警
                    f"query_log 写入失败 log_id={log_id} conv={body.conversation_id}: {log_err}"
                )

    return EventSourceResponse(event_generator())      # 以 SSE 返回事件流


# 从最终状态提取各字段并写入查询日志
async def _write_query_log(
    log_id: str,             # 日志 id
    t0: float,               # 起始时间
    body: ChatRequest,       # 请求体
    final_state: dict | None,  # 工作流最终状态
    error_msg: str | None,   # 错误信息
    user_id: str,
) -> bool:
    """从 final_state 提取所有字段，一次性 INSERT 到 query_log 表。

    成功时在发送反馈 ID 前调用，失败/取消时在 finally 兜底。
    返回是否实际写入，未初始化 Store 时返回 False。
    final_state 为 None 时（异常或客户端断开），关键字段写 NULL。
    """
    query_log_store = get_query_log_store()            # 获取日志存储
    if query_log_store is None:                        # 未初始化
        # 测试环境可能未初始化，跳过落库
        return False                                   # 返回未写入

    # 从 final_state 提取字段（None 时全填 None/默认值）
    if final_state:                                    # 有正常结束状态
        rewritten_query = final_state.get("rewritten_query")  # 改写后查询
        route_path = final_state.get("route_path")     # 路由路径
        rewrite_count = final_state.get("correction_count", 0) or 0  # 纠正次数
        # Select the same final-route evidence that the API exposes.  This
        # prevents stale local results from being logged after a CRAG fallback
        # ends on the online route and filters provider-error placeholders.
        retrieval_result = _sources_for_state(final_state)  # 选取最终证据
        retrieved_doc_ids = json.dumps(                # 序列化证据来源标识
            [
                r.get("source") or r.get("title") or r.get("url") or r.get("id")  # 取最合适的身份字段
                for r in retrieval_result
                if isinstance(r, dict)                 # 仅处理字典
            ],
            ensure_ascii=False,                        # 保留非 ASCII
        )
        avg_reranker_score = final_state.get("avg_reranker_score")  # 重排平均分
        judge_log = final_state.get("judge_log", []) or []  # 判断日志
        final_answer = final_state.get("final_answer") # 最终回答
        answer_length = len(final_answer) if final_answer else 0  # 回答长度
        has_source = 1 if final_answer and ("[来源：" in final_answer or "【来源：" in final_answer) else 0  # 是否含来源标注
        models_used_json = json.dumps(                 # 序列化所用模型
            _infer_models_used(route_path or ""), ensure_ascii=False  # 推断
        )
        fault_key = _derive_fault_key(final_state)     # 阶段 2: 故障标识（排查失败计数归属）
        safety_flag = final_state.get("safety_flag")
        safety_level = final_state.get("safety_level")
        safety_situation = final_state.get("safety_situation")
        escalation_required = final_state.get("escalation_required")
        intent = final_state.get("intent")
        metadata_constraints = final_state.get("metadata_constraints")
        document_type_priority = final_state.get("document_type_priority")
    else:                                              # 异常/断开，字段填空
        rewritten_query = None                         # 改写后查询置空
        route_path = None                              # 路由置空
        rewrite_count = 0                              # 纠正次数归零
        retrieved_doc_ids = None                       # 检索 ids 置空
        avg_reranker_score = None                      # 平均分置空
        judge_log = []                                 # 判断日志置空列表
        final_answer = None                            # 回答置空
        answer_length = 0                              # 长度归零
        has_source = 0                                 # 来源标记归零
        models_used_json = None                        # 模型置空
        fault_key = None                               # 阶段 2: 故障标识置空
        safety_flag = None
        safety_level = None
        safety_situation = None
        escalation_required = None
        intent = None
        metadata_constraints = None
        document_type_priority = None

    record = QueryLogCreate(                           # 构造日志记录
        id=log_id,                                     # 日志 id
        conversation_id=body.conversation_id,          # 会话 id
        user_id=user_id,
        user_label=body.user_label,                    # 提问者标识
        raw_query=body.message,                        # 原始问题
        rewritten_query=rewritten_query,               # 改写后查询
        route_path=route_path,                         # 路由路径
        rewrite_count=rewrite_count,                   # 纠正次数
        retrieved_doc_ids=retrieved_doc_ids,           # 检索文档 ids
        avg_reranker_score=avg_reranker_score,         # 重排平均分
        judge_log_json=json.dumps(judge_log, ensure_ascii=False),  # 判断日志 JSON
        final_answer=final_answer,                     # 最终回答
        answer_length=answer_length,                   # 回答长度
        has_source=has_source,                         # 是否含来源
        models_used_json=models_used_json,             # 所用模型
        token_usage_json=None,  # 本轮预留，P2 阶段填充  # token 用量预留
        fault_key=fault_key,                           # 阶段 2: 故障标识（计数归属）
        safety_flag=safety_flag,
        safety_level=safety_level,
        safety_situation=safety_situation,
        escalation_required=escalation_required,
        intent=intent,
        metadata_constraints=metadata_constraints,
        document_type_priority=document_type_priority,
        latency_ms=int((time.time() - t0) * 1000),     # 总延迟毫秒
        error=error_msg,                               # 错误信息
        created_at=datetime.now(timezone.utc).isoformat(),  # 创建时间
    )
    await query_log_store.insert(record)               # 写入日志表
    return True                                        # 返回写入成功
