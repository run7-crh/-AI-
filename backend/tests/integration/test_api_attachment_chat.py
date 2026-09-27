import json

import pytest
from httpx import ASGITransport, AsyncClient
from asgi_lifespan import LifespanManager

from app.main import app, get_attachment_store
from tests.integration.conftest import login_admin


async def _events(response):
    values = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            values.append(json.loads(line[5:].strip()))
    return values


@pytest.mark.asyncio
async def test_explicit_attachment_is_current_round_context_and_public_metadata_only(monkeypatch):
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await login_admin(client)
            conversation = (await client.post("/api/conversations", json={})).json()["id"]
            attachment_store = get_attachment_store()
            record = await attachment_store.create_attachment(
                conversation, "notes.txt", b"private attachment body", "text/plain"
            )
            await attachment_store.extract_attachment(conversation, record.id)
            captured = {}

            async def stream(input_state, *args, **kwargs):
                captured.update(input_state)
                yield {
                    "event": "on_chain_end",
                    "name": "LangGraph",
                    "data": {"output": {
                        "final_answer": "已参考附件",
                        "route_path": "local",
                        "judge_log": [],
                        "attachment_evidence": input_state["attachment_evidence"],
                        "safety_flag": True,
                        "safety_level": "high",
                        "escalation_required": True,
                    }},
                }

            from app.api import chat as chat_module
            monkeypatch.setattr(chat_module, "get_graph", lambda: type("G", (), {"astream_events": staticmethod(stream)})())
            response = await client.post(
                "/api/chat",
                json={"conversation_id": conversation, "message": "电池鼓包怎么办", "attachment_ids": [record.id]},
            )
            assert response.status_code == 200
            events = await _events(response)
            assert captured["attachment_ids"] == [record.id]
            assert "private attachment body" in captured["attachment_context"]
            attachment_events = [event for event in events if event["type"] == "attachment"]
            assert attachment_events
            assert attachment_events[0]["data"]["status"] == "ready"
            assert attachment_events[0]["data"]["attachment_ids"] == [record.id]
            source = next(event["data"]["sources"][0] for event in events if event["type"] == "meta")
            assert source["source_type"] == "attachment"
            assert source["source_id"] == f"ATTACHMENT:{record.id}"
            assert source["content"] != "private attachment body"
            meta = next(event["data"] for event in events if event["type"] == "meta")
            assert meta["safety_level"] == "high"
            assert meta["escalation_required"] is True


@pytest.mark.asyncio
async def test_empty_message_is_allowed_when_attachment_is_selected(monkeypatch):
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await login_admin(client)
            conversation = (await client.post("/api/conversations", json={})).json()["id"]
            attachment_store = get_attachment_store()
            record = await attachment_store.create_attachment(
                conversation, "notes.txt", "请分析这份售后日志".encode("utf-8"), "text/plain"
            )
            await attachment_store.extract_attachment(conversation, record.id)
            captured = {}

            async def stream(input_state, *args, **kwargs):
                captured.update(input_state)
                yield {
                    "event": "on_chain_end",
                    "name": "LangGraph",
                    "data": {"output": {"final_answer": "已读取附件", "route_path": "local", "judge_log": []}},
                }

            from app.api import chat as chat_module
            monkeypatch.setattr(chat_module, "get_graph", lambda: type("G", (), {"astream_events": staticmethod(stream)})())
            response = await client.post(
                "/api/chat",
                json={"conversation_id": conversation, "message": "", "attachment_ids": [record.id]},
            )
            assert response.status_code == 200
            assert captured["query"] == ""


@pytest.mark.asyncio
async def test_history_returns_attachment_summary_without_private_payload():
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await login_admin(client)
            conversation = (await client.post("/api/conversations", json={})).json()["id"]
            attachment_store = get_attachment_store()
            record = await attachment_store.create_attachment(
                conversation, "notes.txt", b"private body", "text/plain"
            )
            await attachment_store.extract_attachment(conversation, record.id)
            # Link through the same message relation used by /api/chat.
            from app.main import get_store
            message_id = await get_store().add_message(conversation, "user", "附件")
            assert await attachment_store.link_message_attachment(conversation, message_id, record.id)

            response = await client.get(f"/api/conversations/{conversation}")
            assert response.status_code == 200
            summary = response.json()["messages"][0]["attachments"][0]
            assert summary["original_name"] == "notes.txt"
            assert summary["status"] == "ready"
            assert "storage_key" not in summary
            assert "private body" not in str(summary)




@pytest.mark.asyncio
async def test_image_observation_is_public_in_sources_and_text_body_stays_masked(monkeypatch):
    """图片观察经 media_type 获得公开证据豁免；文本附件正文保持掩码。"""
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await login_admin(client)
            conversation = (await client.post("/api/conversations", json={})).json()["id"]
            attachment_store = get_attachment_store()

            class StubVision:
                async def observe(self, payload, detected_mime):
                    from app.services.vision_service import VisualObservation

                    return VisualObservation(
                        image_type="physical",
                        objects=["桨叶"],
                        damage_signals=["桨叶末端缺口"],
                    )

            monkeypatch.setattr(attachment_store, "allow_image_attachments", True)
            image = await attachment_store.create_attachment(
                conversation, "crash.png", b"\x89PNG\r\n\x1a\n" + b"frame", "image/png"
            )
            text = await attachment_store.create_attachment(
                conversation, "notes.txt", b"private text body", "text/plain"
            )
            await attachment_store.extract_attachment(conversation, image.id, vision=StubVision())
            await attachment_store.extract_attachment(conversation, text.id)

            async def stream(input_state, *args, **kwargs):
                yield {
                    "event": "on_chain_end",
                    "name": "LangGraph",
                    "data": {"output": {
                        "final_answer": "已参考附件",
                        "route_path": "local",
                        "judge_log": [],
                        "attachment_evidence": input_state["attachment_evidence"],
                        "safety_flag": False,
                        "safety_level": "low",
                        "escalation_required": False,
                    }},
                }

            from app.api import chat as chat_module
            monkeypatch.setattr(chat_module, "get_graph", lambda: type("G", (), {"astream_events": staticmethod(stream)})())
            response = await client.post(
                "/api/chat",
                json={"conversation_id": conversation, "message": "看看图片", "attachment_ids": [image.id, text.id]},
            )
            assert response.status_code == 200
            events = await _events(response)
            meta = next(event for event in events if event["type"] == "meta")
            sources = meta["data"]["sources"]
            image_source = next(item for item in sources if item.get("media_type") == "image")
            assert "[可见异常] 桨叶末端缺口" in image_source["content"]
            text_source = next(
                item for item in sources
                if item.get("source_type") == "attachment" and item.get("media_type") != "image"
            )
            assert "private text body" not in text_source["content"]
            assert text_source["content"] == "附件正文仅用于当前轮，未持久化"
