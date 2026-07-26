from typing import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel
from app.config import settings


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
