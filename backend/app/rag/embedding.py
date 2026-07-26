# backend/app/rag/embedding.py
"""LlamaIndex embedding 模型配置：华为云 MaaS。

华为云 MaaS 提供 OpenAI 兼容的 embedding 接口：
- Endpoint: {HUAWEI_BASE_URL}/v1/embeddings
- 模型: bge-large-zh-v1.5（输出维度 1024）

LlamaIndex 内置的 OpenAIEmbedding 会把 model 参数转成枚举校验，
拒绝非 OpenAI 官方模型名（如 bge-large-zh-v1.5），
因此这里用 BaseEmbedding 子类直接调 openai 库绕过限制。
"""
import logging
from typing import Any, Sequence
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core import Settings
from openai import OpenAI
from app.config import settings

logger = logging.getLogger(__name__)


class HuaweiMaaSEmbedding(BaseEmbedding):
    """华为云 MaaS embedding（OpenAI 兼容接口）。

    bge-large-zh-v1.5 输出维度 1024。
    """

    api_base: str = ""
    api_key: str = ""
    model_name_: str = ""
    embed_dim: int = 1024

    def __init__(self, **data: Any):
        super().__init__(**data)
        # 用 OpenAI 客户端复用连接池
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.api_base,
        )

    @classmethod
    def class_name(cls) -> str:
        return "HuaweiMaaSEmbedding"

    def _get_query_embedding(self, query: str) -> list[float]:
        resp = self._client.embeddings.create(model=self.model_name_, input=query)
        return list(resp.data[0].embedding)

    def _get_text_embedding(self, text: str) -> list[float]:
        resp = self._client.embeddings.create(model=self.model_name_, input=text)
        return list(resp.data[0].embedding)

    def _get_text_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        # 批量调用，bge 支持一次传多个 input
        resp = self._client.embeddings.create(model=self.model_name_, input=list(texts))
        # 按 index 排序确保顺序
        sorted_data = sorted(resp.data, key=lambda x: x.index)
        return [list(d.embedding) for d in sorted_data]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        # BaseEmbedding 默认会 fallback 到同步实现，这里不强制实现异步
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

    async def _aget_text_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        return self._get_text_embeddings(texts)


def configure_embedding() -> None:
    """配置 LlamaIndex 全局 embedding 模型为华为云 MaaS。

    必须在 Indexer.build() / VectorStoreIndex.from_documents() 之前调用。
    """
    api_base = settings.HUAWEI_BASE_URL.rstrip("/") + "/v1"
    embed_model = HuaweiMaaSEmbedding(
        api_base=api_base,
        api_key=settings.HUAWEI_API_KEY,
        model_name_=settings.EMBEDDING_MODEL,
        embed_dim=1024,
    )
    Settings.embed_model = embed_model
    logger.info(
        f"Embedding 配置完成: model={settings.EMBEDDING_MODEL}, "
        f"api_base={api_base}, embed_dim=1024"
    )


# 模块导入时自动配置（确保 LlamaIndex 任何时候使用 embedding 都用华为云）
configure_embedding()
