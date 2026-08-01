import torch
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.retrievers import VectorIndexRetriever
from sentence_transformers import CrossEncoder

from app.config import settings


# 模块级缓存：CrossEncoder 模型约 2GB，避免重复加载
_cross_encoder_cache: dict[str, CrossEncoder] = {}


def get_cross_encoder(model_name: str) -> CrossEncoder:
    """获取（必要时加载）CrossEncoder 实例，模块级缓存。

    首次调用会从 HuggingFace Hub 下载模型（约 2GB）到 RERANKER_CACHE_DIR，
    后续从缓存加载。GPU 可用时自动使用 CUDA。
    """
    if model_name not in _cross_encoder_cache:
        _cross_encoder_cache[model_name] = CrossEncoder(
            model_name,
            cache_folder=settings.RERANKER_CACHE_DIR,
            device="cuda" if torch.cuda.is_available() else "cpu",
        )
    return _cross_encoder_cache[model_name]


class BGEReranker(BaseNodePostprocessor):
    """本地 BGE Reranker（bge-reranker-v2-m3），基于 sentence-transformers CrossEncoder。

    与 embedding（本地 BAAI/bge-large-zh-v1.5）架构一致，离线可用。
    """

    @classmethod
    def class_name(cls) -> str:
        return "BGEReranker"

    def _postprocess_nodes(self, nodes, query_str=None, query_bundle=None):
        if not nodes:
            return []
        # BaseNodePostprocessor.postprocess_nodes 会把 query_str 转成 QueryBundle
        # 然后以位置参数形式调用本方法，因此 query_str 实际可能收到一个 QueryBundle
        if query_str is not None and not isinstance(query_str, str):
            query_bundle = query_str
            query_str = query_bundle.query_str
        if query_str is None and query_bundle is not None:
            query_str = query_bundle.query_str

        texts = [node.node.get_content() for node in nodes]
        model = get_cross_encoder(settings.RERANKER_MODEL)
        # CrossEncoder.predict 接受 (query, document) 对列表，返回相关性分数
        scores = model.predict([(query_str, t) for t in texts])
        for i, node in enumerate(nodes):
            node.score = float(scores[i])
        return sorted(nodes, key=lambda x: x.score or 0, reverse=True)


class RAGRetriever:
    """统一检索器：向量检索 + Reranking。"""

    def __init__(self, index, top_k: int = 3):
        self.retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=top_k * 3,
        )
        self.reranker = BGEReranker()
        self.final_top_k = top_k

    def retrieve(self, query: str) -> list:
        nodes = self.retriever.retrieve(query)
        reranked = self.reranker.postprocess_nodes(nodes, query_str=query)
        final = reranked[:self.final_top_k]
        return [
            {
                "content": node.node.get_content(),
                "source": node.node.metadata.get("file_name", "未知"),
                "title": node.node.metadata.get("title", ""),
                "score": node.score or 0,
            }
            for node in final
        ]
