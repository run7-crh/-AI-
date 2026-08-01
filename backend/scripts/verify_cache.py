"""验证 D 盘模型缓存完整性（不联网）。

强制离线模式，加载 embedding + reranker，并执行一次推理。
若全部通过，则 D 盘缓存完整可用，C 盘冗余可安全删除。

运行方式（在 backend 目录下）:
    python scripts/verify_cache.py
"""
import os
import sys
from pathlib import Path

# 强制离线：任何联网尝试都会立即失败，而不是回退到下载
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

# Settings 必需的 API key（验证缓存用，给占位即可）
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-placeholder")
os.environ.setdefault("TAVILY_API_KEY", "tvly-placeholder")

# P2-4: 用相对路径替代硬编码绝对路径
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.config import settings


def main() -> None:
    print(f"EMBEDDING_CACHE_DIR = {settings.EMBEDDING_CACHE_DIR}")
    print(f"RERANKER_CACHE_DIR  = {settings.RERANKER_CACHE_DIR}")
    print()

    # --- 1. Embedding ---
    print("[1/2] 加载 BGE embedding (bge-large-zh-v1.5)...")
    from app.rag.embedding import configure_embedding, EMBED_DIM
    from llama_index.core import Settings as LISettings

    configure_embedding()
    embed_model = LISettings.embed_model
    vec = embed_model.get_text_embedding("什么是 RAG？")
    assert len(vec) == EMBED_DIM, f"维度不符: {len(vec)} != {EMBED_DIM}"
    print(f"  OK: 向量维度={len(vec)}, 前3维={vec[:3]}")
    print()

    # --- 2. Reranker ---
    print("[2/2] 加载 BGE reranker (bge-reranker-v2-m3)...")
    from app.rag.retriever import get_cross_encoder
    from app.config import settings as _s

    ce = get_cross_encoder(_s.RERANKER_MODEL)
    scores = ce.predict([("什么是 RAG？", "检索增强生成是用于提升模型回答准确性的技术。")])
    assert len(scores) == 1
    print(f"  OK: reranker score={float(scores[0]):.4f}")
    print()

    print("=== 全部通过：D 盘缓存完整可用，可安全删除 C 盘冗余 ===")


if __name__ == "__main__":
    main()
