from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb
from pathlib import Path
from app.rag.readers import ObsidianMarkdownReader
from app.rag.retriever import RAGRetriever
# 导入即触发 embedding 配置（华为云 MaaS），避免 LlamaIndex 默认用 OpenAI
from app.rag import embedding  # noqa: F401


class Indexer:
    """索引构建器。"""

    def __init__(self, data_dir: str, persist_dir: str):
        self.data_dir = Path(data_dir)
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.db = chromadb.PersistentClient(path=str(self.persist_dir))
        self.chroma_collection = self.db.get_or_create_collection("obsidian_kb")
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
        try:
            self.index = VectorStoreIndex.from_vector_store(
                self.vector_store,
                storage_context=self.storage_context,
            )
        except Exception:
            self.build()

    def update(self, file_name: str):
        self.chroma_collection.delete(where={"file_name": file_name})
        reader = ObsidianMarkdownReader()
        file_path = self.data_dir / file_name
        if file_path.exists():
            docs = reader.load_data(file_path=file_path)
            for doc in docs:
                self.index.insert(doc)

    def get_retriever(self):
        return RAGRetriever(self.index, top_k=3)
