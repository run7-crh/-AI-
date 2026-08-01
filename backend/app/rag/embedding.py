# backend/app/rag/embedding.py
"""LlamaIndex embedding 模型配置：本地 HuggingFace BGE。

原设计用华为云 MaaS 的 bge-large-zh-v1.5，但账号下未提供 embedding 模型权限，
改为本地 HuggingFace 推理（同模型 `BAAI/bge-large-zh-v1.5`，输出维度 1024）。

首次运行会从 HuggingFace Hub 下载模型（约 1.3GB），后续从本地缓存加载。
"""
import logging
from llama_index.core import Settings
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

from app.config import settings

logger = logging.getLogger(__name__)

# bge-large-zh-v1.5 输出维度
EMBED_DIM = 1024
# HuggingFace 模型 ID
HF_MODEL_NAME = "BAAI/bge-large-zh-v1.5"


def configure_embedding() -> None:
    """配置 LlamaIndex 全局 embedding 模型为本地 HuggingFace BGE。

    必须在 Indexer.build() / VectorStoreIndex.from_documents() 之前调用。
    首次调用会触发模型下载（约 1.3GB）。

    P2-2: 移除模块导入时的自动调用，改为由 Indexer.__init__ 显式调用，
    避免任何 import（含测试 mock）触发模型加载。
    """
    embed_model = HuggingFaceEmbedding(
        model_name=HF_MODEL_NAME,
        cache_folder=settings.EMBEDDING_CACHE_DIR,
    )
    Settings.embed_model = embed_model
    logger.info(
        f"Embedding 配置完成: model={HF_MODEL_NAME}, "
        f"embed_dim={EMBED_DIM}, backend=local-huggingface, "
        f"cache_dir={settings.EMBEDDING_CACHE_DIR}"
    )
