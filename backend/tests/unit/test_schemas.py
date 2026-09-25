import pytest
from datetime import datetime
from pydantic import ValidationError
from app.models.schemas import ChatRequest, ConversationCreate, ConversationUpdate

def test_chat_request_valid():
    req = ChatRequest(conversation_id="abc", message="你好")
    assert req.conversation_id == "abc"
    assert req.message == "你好"
    assert req.attachment_ids is None

def test_chat_request_rejects_empty_message():
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id="abc", message="")


def test_chat_request_allows_empty_message_when_attachment_is_selected():
    req = ChatRequest(conversation_id="abc", message="", attachment_ids=["att_1"])
    assert req.message == ""
    assert req.attachment_ids == ["att_1"]

def test_chat_request_rejects_too_long_message():
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id="abc", message="x" * 2001)

def test_conversation_create_optional_title():
    c = ConversationCreate()
    assert c.title is None
    c2 = ConversationCreate(title="测试")
    assert c2.title == "测试"

def test_conversation_update_requires_title():
    with pytest.raises(ValidationError):
        ConversationUpdate()
