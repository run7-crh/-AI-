import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.graph.tools import call_llm

@pytest.mark.asyncio
async def test_call_llm_returns_text():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "测试回复"
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        result = await call_llm("system", "user", temperature=0.5)
    assert result["text"] == "测试回复"
    assert result["structured"] is None

@pytest.mark.asyncio
async def test_call_llm_with_history_passes_messages():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = "回复"
    mock_llm.ainvoke = AsyncMock(return_value=mock_response)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        await call_llm("system", "user", history=[{"role": "user", "content": "历史"}])
    mock_llm.ainvoke.assert_called_once()
    msgs = mock_llm.ainvoke.call_args.args[0]
    assert len(msgs) >= 3  # system + history + user

@pytest.mark.asyncio
async def test_call_llm_with_schema_returns_structured():
    from pydantic import BaseModel
    class TestSchema(BaseModel):
        passed: bool
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.passed = True
    mock_structured.model_dump = MagicMock(return_value={"passed": True})
    structured_llm = MagicMock()
    structured_llm.ainvoke = AsyncMock(return_value=mock_structured)
    mock_llm.with_structured_output = MagicMock(return_value=structured_llm)
    with patch("app.graph.tools.ChatOpenAI", return_value=mock_llm):
        result = await call_llm("system", "user", output_schema=TestSchema)
    assert result["structured"]["passed"] is True
