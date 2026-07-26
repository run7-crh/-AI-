# backend/app/graph/nodes.py
import logging

from app.graph.state import AgentState
from app.graph.tools import call_llm, evaluate, retrieve, tavily_search
from app.graph.prompts import (
    REWRITE_PROMPT, DECOMPOSE_PROMPT, MULTI_STEP_PROMPT,
    LOCAL_GEN_PROMPT, ONLINE_GEN_PROMPT,
)
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)


class DecomposeSchema(BaseModel):
    needs_decomposition: bool
    reasoning_steps: list[dict]


async def rewrite_query_node(state: AgentState) -> dict:
    result = await call_llm(
        system_prompt=REWRITE_PROMPT,
        user_input=state["query"],
        temperature=0.7,
        history=state.get("history", []),
        model=settings.MODEL_FLASH,
    )
    return {"rewritten_query": result["text"]}


async def decompose_question_node(state: AgentState) -> dict:
    result = await call_llm(
        system_prompt=DECOMPOSE_PROMPT,
        user_input=state["rewritten_query"],
        temperature=0.3,
        output_schema=DecomposeSchema,
        model=settings.MODEL_FLASH,
    )
    structured = result["structured"]
    return {
        "needs_decomposition": structured["needs_decomposition"],
        "reasoning_steps": structured["reasoning_steps"],
    }


async def multi_step_reason_node(state: AgentState) -> dict:
    """多步推理节点。

    修复设计问题 1：直接写 final_answer，主图连到 END。
    """
    steps_text = "\n".join([f"- {s.get('sub_query', '')}" for s in state["reasoning_steps"]])
    user_input = f"原始问题：{state['query']}\n\n分解的子问题：\n{steps_text}\n\n请逐步推理并给出最终答案。"

    result = await call_llm(
        system_prompt=MULTI_STEP_PROMPT,
        user_input=user_input,
        temperature=0.5,
        history=state.get("history", []),
        model=settings.MODEL_PRO_REASON,
    )
    return {
        "final_answer": result["text"],
        "route_path": "decomposition",
        "reasoning_result": result["text"],
    }


async def judge_relevance_node(state: AgentState) -> dict:
    result = await evaluate(
        judge_type="is_relevant",
        source="",
        query=state["rewritten_query"],
    )
    return {"is_relevant": result["passed"], "judge_log": [result]}


async def rag_retrieve_node(state: AgentState, rag_retriever) -> dict:
    """检索 + RAG 质量评估（生成前）。"""
    # 1. 检索
    retrieval_result = await retrieve(state["rewritten_query"], rag_retriever)

    # 2. RAG 质量评估
    source_text = "\n\n".join([r["content"] for r in retrieval_result])
    quality_judge = await evaluate(
        judge_type="is_quality_pass",
        source=source_text,
        query=state["rewritten_query"],
    )

    return {
        "retrieval_result": retrieval_result,
        "rag_quality_pass": quality_judge["passed"],
        "judge_log": [quality_judge],
    }


async def web_search_node(state: AgentState) -> dict:
    result = await tavily_search(state["rewritten_query"])
    return {"web_search_result": result}


async def generate_answer_node(state: AgentState) -> dict:
    """统一生成节点：根据是否走 web 路径选提示词。

    用 key 存在性判断而非 truthy：Tavily 返回空字符串 "" 时仍应走 online 分支，
    否则会错误地走 local 分支并访问不存在的 retrieval_result 导致 KeyError。
    """
    if "web_search_result" in state:
        # 联网路径
        prompt = ONLINE_GEN_PROMPT.format(
            query=state["rewritten_query"],
            search_result=state["web_search_result"],
        )
        result = await call_llm(
            system_prompt=prompt,
            user_input=state["query"],
            temperature=0.7,
            history=state.get("history", []),
            model=settings.MODEL_PRO_CHAT,
        )
        return {
            "online_answer": result["text"],
            "final_answer": result["text"],
            "route_path": "online",
        }
    else:
        # 知识库路径
        context = "\n\n".join([
            f"[{i+1}] {r['content']}" for i, r in enumerate(state["retrieval_result"])
        ])
        prompt = LOCAL_GEN_PROMPT.format(
            query=state["rewritten_query"],
            context=context,
        )
        result = await call_llm(
            system_prompt=prompt,
            user_input=state["query"],
            temperature=0.7,
            history=state.get("history", []),
            model=settings.MODEL_PRO_CHAT,
        )
        return {
            "local_answer": result["text"],
            "final_answer": result["text"],
            "route_path": "local",
        }


async def quality_gate_node(state: AgentState) -> dict:
    """生成后质量门控：幻觉检测 + 答案质量评估。

    retry 已下沉到 tools.evaluate，本节点只做 try/except 降级：
    若 evaluate 重试 2 次仍失败，则降级到"质量不通过"。
    返回只含需更新字段的 dict（与其他节点风格一致），
    避免直接修改入参 state 导致 LangGraph add reducer 重复 append judge_log。
    """
    try:
        source = (state["retrieval_result"] if state["route_path"] == "local"
                  else state["web_search_result"])
        answer = (state["local_answer"] if state["route_path"] == "local"
                  else state["online_answer"])

        # 1. 幻觉检测
        halluc_judge = await evaluate(
            judge_type="is_hallucination",
            source=source, answer=answer, query=state["rewritten_query"],
        )

        # 2. 答案质量评估
        quality_judge = await evaluate(
            judge_type="is_quality_pass",
            source=source, answer=answer, query=state["rewritten_query"],
        )

        # 综合：质量通过 = 无幻觉 AND 答案质量通过
        return {
            "hallucination_flag": halluc_judge["passed"],
            "answer_quality_pass": (not halluc_judge["passed"]) and quality_judge["passed"],
            "judge_log": [halluc_judge, quality_judge],
        }
    except Exception as e:
        logger.warning(f"质量门控失败，降级到不通过: {e}")
        return {
            "answer_quality_pass": False,
            "hallucination_flag": True,
            "judge_log": [{
                "judge_type": "fallback",
                "passed": False,
                "raw_output": {"error": str(e)},
            }],
        }
