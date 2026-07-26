from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle


class HuaweiReranker(BaseNodePostprocessor):
    """华为云 MaaS bge-reranker-v2-m3 重排器。"""

    @classmethod
    def class_name(cls) -> str:
        return "HuaweiReranker"

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
        rerank_result = self._call_huawei_rerank(query_str, texts)
        scores = rerank_result.get("scores", [])
        for i, node in enumerate(nodes):
            if i < len(scores):
                node.score = scores[i]
        return sorted(nodes, key=lambda x: x.score or 0, reverse=True)

    def _call_huawei_rerank(self, query: str, documents: list) -> dict:
        """调用华为云 MaaS rerank API。

        TODO: 根据华为云 MaaS 实际 API 文档补充 endpoint 和请求格式。
        当前为占位实现，返回固定分数（按输入顺序递减）。
        """
        from app.config import settings
        # 占位实现：返回按顺序递减的分数
        # 实际应调用华为云 MaaS rerank API（httpx）
        return {"scores": [1.0 - i * 0.1 for i in range(len(documents))]}
