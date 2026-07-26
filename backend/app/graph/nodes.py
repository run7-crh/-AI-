# backend/app/graph/nodes.py
from app.graph.state import AgentState
from app.graph.tools import call_llm, evaluate, retrieve, tavily_search
from app.graph.prompts import (
    REWRITE_PROMPT, DECOMPOSE_PROMPT, MULTI_STEP_PROMPT,
    LOCAL_GEN_PROMPT, ONLINE_GEN_PROMPT,
)
from pydantic import BaseModel
from app.config import settings


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
