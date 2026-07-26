from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel
from app.config import settings
from app.graph.prompts import IS_RELEVANT_PROMPT, IS_QUALITY_PASS_PROMPT, IS_HALLUCINATION_PROMPT


JUDGE_PROMPTS = {
    "is_relevant": IS_RELEVANT_PROMPT,
    "is_quality_pass": IS_QUALITY_PASS_PROMPT,
    "is_hallucination": IS_HALLUCINATION_PROMPT,
}


class JudgeSchema(BaseModel):
    passed: bool
    reason: str


async def call_llm(
    system_prompt: str,
    user_input: str,
    temperature: float = 0.3,
    output_schema: Optional[type[BaseModel]] = None,
    history: list[dict] = None,
    model: str = "deepseek-chat",
) -> dict:
    """统一 LLM 调用工具。"""
    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
    )

    messages = [SystemMessage(content=system_prompt)]
    if history:
        for h in history:
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
            else:
                messages.append(AIMessage(content=h["content"]))
    messages.append(HumanMessage(content=user_input))

    if output_schema:
        structured_llm = llm.with_structured_output(output_schema)
        result = await structured_llm.ainvoke(messages)
        # Pydantic V2 模型转 dict
        if hasattr(result, "model_dump"):
            return {"text": "", "structured": result.model_dump()}
        return {"text": "", "structured": dict(result)}

    response = await llm.ainvoke(messages)
    return {"text": response.content, "structured": None}


async def evaluate(judge_type: str, source: str, answer: str = "", query: str = "") -> dict:
    """统一评估工具。全部用 temp=0.2（修复温度不一致问题）。"""
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
