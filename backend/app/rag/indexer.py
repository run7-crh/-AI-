from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb
import logging
from pathlib import Path
from app.config import settings
from app.rag.readers import ObsidianMarkdownReader
from app.rag.retriever import RAGRetriever
from app.rag.embedding import configure_embedding

logger = logging.getLogger(__name__)


class Indexer:
    """索引构建器。"""

    def __init__(self, data_dir: str, persist_dir: str):
        self.data_dir = Path(data_dir)
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # P2-2: 显式调用 configure_embedding()，替代原模块导入副作用
        # 确保任何使用 embedding 的场景都走本地 BGE，而非 LlamaIndex 默认 OpenAI
        configure_embedding()

        # 显式设置 chunk 策略（LlamaIndex 默认 chunk_size=1024, chunk_overlap=20 过大）
        Settings.chunk_size = 512
        Settings.chunk_overlap = 50

        self.db = chromadb.PersistentClient(path=str(self.persist_dir))
        # P2-12: collection 名从 config 读取（默认 obsidian_kb，向后兼容）
        self.chroma_collection = self.db.get_or_create_collection(
            settings.CHROMA_COLLECTION_NAME
        )
        self.vector_store = ChromaVectorStore(chroma_collection=self.chroma_collection)
        self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
        self.index = None

    def build(self):
        reader = ObsidianMarkdownReader()
        documents = []
        for md_file in self.data_dir.glob("*.md"):
            documents.extend(reader.load_data(file_path=md_file))

        self.index = VectorStoreIndex.from_documents(
            documents,
            storage_context=self.storage_context,
            show_progress=True,
        )

    def load_or_build(self):
        """加载已有索引；若 collection 为空或加载失败则重建。

        原实现缺陷：from_vector_store 对空 collection 不报错，
        导致知识库目录缺失/为空时静默加载空索引，所有检索返回空。
        """
        existing_count = self.chroma_collection.count()
        if existing_count == 0:
            # 空索引，必须 rebuild
            logger.info(f"Chroma collection 为空（count=0），触发 rebuild")
            self.build()
            return
        try:
            self.index = VectorStoreIndex.from_vector_store(
                self.vector_store,
                storage_context=self.storage_context,
            )
        except Exception as e:
            logger.warning(f"加载已有索引失败（{e}），触发 rebuild")
            self.build()

    def get_retriever(self):
        return RAGRetriever(self.index, top_k=3)
