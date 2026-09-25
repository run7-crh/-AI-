# backend/app/rag/retriever.py
# 导入 PyTorch，用于判断 GPU 是否可用（决定 reranker 运行在 cuda 还是 cpu）
import torch
# 导入 threading，用于模型加载与推理的线程锁，避免并发访问
import threading
# 导入 LlamaIndex 的基础节点后处理器基类，供 reranker 继承
from llama_index.core.postprocessor.types import BaseNodePostprocessor
# 导入 LlamaIndex 的向量索引检索器
from llama_index.core.retrievers import VectorIndexRetriever
# 导入 sentence-transformers 的交叉编码器，作为本地 reranker 的底层模型
from sentence_transformers import CrossEncoder

# 导入全局配置
from app.config import settings
# 导入证据数据模型
from app.models.evidence import Evidence


# 模块级缓存：CrossEncoder 模型约 2GB，避免重复加载
_cross_encoder_cache: dict[str, CrossEncoder] = {}  # 以模型名为键缓存已加载的编码器
_cross_encoder_lock = threading.Lock()              # 保护缓存与推理的全局锁


# 定义获取 CrossEncoder 实例的函数（带模块级缓存）
def get_cross_encoder(model_name: str) -> CrossEncoder:
    """获取（必要时加载）CrossEncoder 实例，模块级缓存。

    首次调用会从 HuggingFace Hub 下载模型（约 2GB）到 RERANKER_CACHE_DIR，
    后续从缓存加载。GPU 可用时自动使用 CUDA。
    """
    if model_name not in _cross_encoder_cache:   # 缓存中尚无该模型
        with _cross_encoder_lock:                # 加锁防止并发重复加载
            if model_name not in _cross_encoder_cache:  # 二次判断（双重检查）
                _cross_encoder_cache[model_name] = CrossEncoder(  # 加载并写入缓存
                    model_name,                 # 模型名
                    cache_folder=settings.RERANKER_CACHE_DIR,  # 缓存目录
                    device="cuda" if torch.cuda.is_available() else "cpu",  # GPU 优先否则 CPU
                )
    return _cross_encoder_cache[model_name]      # 返回缓存的模型实例


# 定义本地 BGE Reranker 类，继承 LlamaIndex 节点后处理器
class BGEReranker(BaseNodePostprocessor):
    """本地 BGE Reranker（bge-reranker-v2-m3），基于 sentence-transformers CrossEncoder。

    与 embedding（本地 BAAI/bge-large-zh-v1.5）架构一致，离线可用。
    """

    @classmethod
    def class_name(cls) -> str:
        return "BGEReranker"                     # 返回类名（LlamaIndex 约定）

    # 后处理节点：给每个节点重排相关性分数
    def _postprocess_nodes(self, nodes, query_str=None, query_bundle=None):
        if not nodes:                            # 无节点可直接返回
            return []
        # BaseNodePostprocessor.postprocess_nodes 会把 query_str 转成 QueryBundle
        # 然后以位置参数形式调用本方法，因此 query_str 实际可能收到一个 QueryBundle
        if query_str is not None and not isinstance(query_str, str):  # 位置参数实际是 QueryBundle
            query_bundle = query_str             # 移交给 query_bundle
            query_str = query_bundle.query_str   # 从 bundle 提取查询串
        if query_str is None and query_bundle is not None:  # 未提供 query 串但给了 bundle
            query_str = query_bundle.query_str   # 从 bundle 提取查询串

        texts = [node.node.get_content() for node in nodes]  # 收集每个节点的文本内容
        model = get_cross_encoder(settings.RERANKER_MODEL)   # 获取（加载）reranker 模型
        # CrossEncoder.predict 接受 (query, document) 对列表，返回相关性分数
        # CrossEncoder is shared by all requests; serialise inference to avoid
        # concurrent GPU/CPU access exhausting the small local runtime.
        with _cross_encoder_lock:                # 加锁串行化推理，防止并发耗尽运行时
            scores = model.predict([(query_str, t) for t in texts])  # 批量打分
        for i, node in enumerate(nodes):         # 遍历节点
            node.score = float(scores[i])        # 写入该节点相关性分数
        return sorted(nodes, key=lambda x: x.score or 0, reverse=True)  # 按分数降序返回


# 定义统一检索器类：向量检索 + Reranking
class RAGRetriever:
    """统一检索器：向量检索 + Reranking。"""

    # 初始化：保存索引并构建向量检索器与 reranker
    def __init__(self, index, top_k: int = 3):
        self.index = index                       # 保存语料索引
        self.retriever = VectorIndexRetriever(   # 创建向量检索器
            index=index,                         # 绑定索引
            similarity_top_k=top_k * 3,          # 先取 3 倍候选待重排
        )
        self.reranker = BGEReranker()            # 创建本地 reranker
        self.final_top_k = top_k                 # 记录最终返回条数

    # 检索执行：向量召回候选并重排，返回证据列表
    @staticmethod
    def _normalise_document_type(value: object) -> str:
        aliases = {"products": "product", "cases": "case"}
        return aliases.get(str(value or "").strip().lower(), str(value or "").strip().lower())

    @classmethod
    def _metadata_matches(cls, item: dict, constraints: dict[str, str], *, generic_only: bool = False) -> bool:
        model = str(item.get("product_model") or "").strip().lower()
        if generic_only:
            requested_model = str(constraints.get("product_model") or "").strip().lower()
            return model in (requested_model, "", "all")
        requested_model = str(constraints.get("product_model") or "").strip().lower()
        if requested_model and model not in (requested_model, "all"):
            return False
        for field in ("component", "fault_type"):
            expected = str(constraints.get(field) or "").strip().lower()
            actual = str(item.get(field) or "").strip().lower()
            if expected and actual != expected:
                return False
        return True

    @classmethod
    def _rank_metadata(cls, item: dict, priority: list[str]) -> float:
        doc_type = cls._normalise_document_type(item.get("document_type"))
        if not priority or doc_type not in [cls._normalise_document_type(p) for p in priority]:
            return 0.0
        rank = [cls._normalise_document_type(p) for p in priority].index(doc_type)
        return max(0.0, 0.12 - rank * 0.04)

    @classmethod
    def _priority_rank(cls, item: dict, priority: list[str]) -> int:
        if not priority:
            return len(priority)
        normalized = [cls._normalise_document_type(p) for p in priority]
        try:
            return normalized.index(cls._normalise_document_type(item.get("document_type")))
        except ValueError:
            return len(normalized)

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        metadata_constraints: dict[str, str] | None = None,
        document_type_priority: list[str] | None = None,
    ) -> list[Evidence]:
        """Retrieve and rerank evidence.

        ``top_k`` is request-scoped.  The old implementation accepted a
        ``top_k`` argument in the graph tool but silently ignored it, causing
        the relevance short-circuit (top-1) to retrieve the normal top-3.
        A request-scoped retriever is created when ``top_k`` differs from the
        configured default.  This avoids mutating the shared retriever while
        another request is running.
        """
        requested_k = self.final_top_k if top_k is None else int(top_k)  # 确定本次请求的目标条数
        if requested_k < 1:                      # 条数非法
            return []
        constrained = bool(metadata_constraints or document_type_priority)
        if constrained:
            # 元数据过滤需要更宽的候选池，才能在过滤后仍有机会回退到通用文档。
            candidate_retriever = VectorIndexRetriever(
                index=self.index,
                similarity_top_k=max(requested_k * 3, 30),
            )
        elif requested_k == self.final_top_k:      # 与默认值一致时复用共享检索器
            candidate_retriever = self.retriever
        else:                                    # 否则创建请求级检索器避免串扰
            candidate_retriever = VectorIndexRetriever(
                index=self.index,                # 绑定索引
                similarity_top_k=requested_k * 3,  # 3 倍候选
            )
        # Explicit assignment also keeps custom/mock retrievers honest when
        # they ignore the constructor argument.
        candidate_retriever.similarity_top_k = requested_k * 3  # 显式覆盖候选数，保证生效
        nodes = candidate_retriever.retrieve(query)  # 执行向量检索取候选
        reranked = self.reranker.postprocess_nodes(nodes, query_str=query)  # 重排
        seen_chunks: set[tuple[str, str]] = set()  # 记录已见过的(来源,内容)以去重
        raw_items: list[dict] = []
        for node in reranked:                    # 遍历重排后的节点
            source = node.node.metadata.get("file_name", "未知")  # 取来源文件名
            content = node.node.get_content()    # 取节点文本内容
            # Existing installations may still contain duplicate UUID records
            # from pre-idempotent rebuilds.  Suppress identical source/content
            # pairs at query time while the next rebuild cleans the collection.
            key = (str(source), content)         # 组合去重键
            if key in seen_chunks:               # 已见过相同来源+内容
                continue                         # 跳过该重复块
            seen_chunks.add(key)                 # 记录该键
            raw_items.append({                   # 先构造成带元数据的证据对象
                "id": node.node.node_id,         # 节点 id
                "source_type": "local",          # 来源类型为本地
                "content": content,              # 文本内容
                "source": source,                # 来源文件
                "title": node.node.metadata.get("title", ""),  # 标题
                "url": None,                     # 无对外链接
                "document_id": node.node.metadata.get("document_id"),  # 所属文档 id
                "chunk_id": node.node.node_id,   # 块 id
                "score": float(node.score) if node.score is not None else 0.0,  # 相关性分数
                # 阶段 1（drone 知识库）：售后身份字段随 Evidence 透出；
                # 旧 collection / obsidian 库无这些 metadata 时为 None，向后兼容。
                "document_type": node.node.metadata.get("document_type"),  # 文档类型
                "product_model": node.node.metadata.get("product_model"),  # 适用机型
                "component": node.node.metadata.get("component"),          # 涉及部件
                "fault_type": node.node.metadata.get("fault_type"),        # 故障类型
                "data_type": node.node.metadata.get("data_type"),          # factual/synthetic
                "source_id": node.node.metadata.get("source_id"),          # 来源登记号
            })
        constraints = {str(k): str(v) for k, v in (metadata_constraints or {}).items() if v not in (None, "")}
        filtered = [item for item in raw_items if self._metadata_matches(item, constraints)]
        # 机型明确时，严格排除其他机型；无命中时重新使用候选中的通用文档，
        # 既完成宽检索回退，又不把其他机型的参数/步骤套给用户。
        if constraints.get("product_model"):
            if not filtered:
                filtered = [item for item in raw_items if self._metadata_matches(item, constraints, generic_only=True)]
        elif constraints:
            # component/fault_type 仅作为软约束：无结果时保留宽检索结果。
            filtered = filtered or raw_items
        else:
            filtered = raw_items
        priority = document_type_priority or []
        filtered.sort(
            key=lambda item: (self._priority_rank(item, priority),
                              -(float(item.get("score") or 0) + self._rank_metadata(item, priority))),
        )
        return filtered[:requested_k]
