"""调试 LangGraph astream_events 的事件类型。

确认 LLM 流式 token 事件的实际名称（on_llm_stream vs on_chat_model_stream）。

运行方式（在 backend 目录下）:
    python scripts/debug_events.py
"""
import asyncio
import os
import sys
from pathlib import Path

# 防止 TRAE sandbox 拦截 .pyc 写入
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# P2-4: 用相对路径替代硬编码绝对路径
# scripts/debug_events.py → backend/
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.rag.indexer import Indexer
from app.graph.builder import build_graph
from app.config import settings


async def main():
    print("初始化索引和图...")
    indexer = Indexer(
        data_dir=settings.KB_DATA_DIR,
        persist_dir=settings.CHROMA_PERSIST_DIR,
    )
    indexer.load_or_build()
    graph = build_graph(indexer.get_retriever())
    print("图构建完成\n")

    input_state = {
        "query": "什么是 RAG？一句话",
        "conversation_id": "debug",
        "history": [],
        "judge_log": [],
    }

    event_types = {}
    token_samples = []

    async for event in graph.astream_events(input_state, version="v2"):
        evt_type = event["event"]
        evt_name = event.get("name", "")

        if evt_type not in event_types:
            event_types[evt_type] = 0
        event_types[evt_type] += 1

        # 收集所有 stream 类事件的样本
        if "stream" in evt_type:
            chunk = event.get("data", {}).get("chunk")
            content = ""
            if hasattr(chunk, "content"):
                content = chunk.content
            elif isinstance(chunk, dict):
                content = chunk.get("content", "")
            if content and len(token_samples) < 10:
                token_samples.append({
                    "event": evt_type,
                    "name": evt_name,
                    "content_preview": content[:50] if isinstance(content, str) else str(content)[:50],
                })

    print("=== 事件类型统计 ===")
    for evt_type, count in sorted(event_types.items()):
        print(f"  {evt_type}: {count}")

    print(f"\n=== Stream 事件样本（前 10）===")
    if token_samples:
        for s in token_samples:
            print(f"  event={s['event']}, name={s['name']}, content={s['content_preview']}")
    else:
        print("  无 stream 事件")


if __name__ == "__main__":
    asyncio.run(main())
