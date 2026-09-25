# backend/app/rag/indexer.py
# 导入 LlamaIndex 核心组件：向量索引、存储上下文、全局配置
from llama_index.core import VectorStoreIndex, StorageContext, Settings
# 导入句子切分器，用于把长文档切成块
from llama_index.core.node_parser import SentenceSplitter
# 导入 Chroma 向量存储适配器
from llama_index.vector_stores.chroma import ChromaVectorStore
# 导入 chromadb，直接操作底层向量数据库
import chromadb
# 导入 json，用于读写索引清单文件
import json
# 导入日志模块
import logging
# 导入 os，用于文件系统操作（fsync、replace）
import os
# 导入正则模块，用于标题键归一化
import re
# 导入 frontmatter，用于检查文档正文
import frontmatter
# 导入 Path，用于路径处理
from pathlib import Path
# 导入 uuid4，用于生成候选 collection 唯一名
from uuid import uuid4
# 导入全局配置与知识库 profile 解析
from app.config import settings, resolve_kb_profile
# 导入知识库读取器：Obsidian 原库读取器 + drone 售后库读取器 + 共用遍历函数
from app.rag.readers import ObsidianMarkdownReader, DroneMarkdownReader, iter_kb_markdown_files
# 导入检索器
from app.rag.retriever import RAGRetriever
# 导入 embedding 配置函数
from app.rag.embedding import configure_embedding

# 获取当前模块日志器
logger = logging.getLogger(__name__)

CHUNK_SIZE = 512                 # 分块大小（字符）
CHUNK_OVERLAP = 50               # 相邻块重叠字符数
MANIFEST_SCHEMA_VERSION = 2      # 索引清单 schema 版本
MIN_BODY_CHARS = 200             # 文档最小有效正文长度


# 定义稳定分块 id 生成函数：由文档 id + 位置索引确定
def _stable_chunk_id(index: int, document) -> str:
    """Build a deterministic chunk ID from its document and position."""

    return f"{document.id_}:chunk:{index}"  # 格式：文档id:chunk:序号


# 定义索引构建器类
class Indexer:
    """索引构建器。"""

    # 初始化：接收数据目录与持久化目录（collection 名与读取器类型可按 profile 注入）
    def __init__(
        self,
        data_dir: str,
        persist_dir: str,
        collection_name: str | None = None,  # Chroma collection 名（缺省用全局配置）
        reader: str = "obsidian",            # 读取器类型："obsidian" / "drone"
    ):
        self.data_dir = Path(data_dir)                  # 数据源目录（.md 文件所在）
        self.persist_dir = Path(persist_dir)            # 索引持久化目录
        self.persist_dir.mkdir(parents=True, exist_ok=True)  # 确保目录存在
        self.reader_kind = reader                       # 记录读取器类型，决定遍历/去重策略

        # P2-2: 显式调用 configure_embedding()，替代原模块导入副作用
        # 确保任何使用 embedding 的场景都走本地 BGE，而非 LlamaIndex 默认 OpenAI
        configure_embedding()                           # 配置全局 embedding 模型

        # 显式设置 chunk 策略（LlamaIndex 默认 chunk_size=1024, chunk_overlap=20 过大）
        # Supplying an id function prevents UUIDs from changing on every
        # rebuild, which makes evidence references stable across runs.
        Settings.node_parser = SentenceSplitter(        # 设置分块解析器
            chunk_size=CHUNK_SIZE,                      # 块大小
            chunk_overlap=CHUNK_OVERLAP,                # 重叠
            id_func=_stable_chunk_id,                   # 稳定 id 函数
        )
        # Keep the public Settings values explicit for callers that inspect
        # the configured policy instead of the parser instance.
        Settings.chunk_size = CHUNK_SIZE                # 显式公开 chunk_size
        Settings.chunk_overlap = CHUNK_OVERLAP          # 显式公开 chunk_overlap
        # ``Settings.transformations`` is lazily cached; refresh it when an
        # Indexer is created so a previously initialised parser cannot leak
        # into this index build.
        Settings.transformations = [Settings.node_parser]  # 刷新变换管线

        self.db = chromadb.PersistentClient(path=str(self.persist_dir))  # 创建持久化 client
        # P2-12: collection 名可注入（profile 解析），缺省沿用全局配置（默认 obsidian_kb）
        self.collection_name = collection_name or settings.CHROMA_COLLECTION_NAME  # 取 collection 名
        self.manifest_path = self.persist_dir / f"{self.collection_name}.active.json"  # 清单文件路径
        self._active_manifest: dict | None = None       # 活动清单缓存
        self._manifest_recovery_required = False        # 是否需恢复清单
        active_name = self._read_active_collection_name()  # 读取当前活动 collection 名
        self.chroma_collection = self._open_collection(active_name)  # 打开该 collection
        self.vector_store = ChromaVectorStore(chroma_collection=self.chroma_collection)  # 创建向量存储
        self.storage_context = StorageContext.from_defaults(vector_store=self.vector_store)  # 存储上下文
        self.index = None                               # 索引对象（稍后加载/构建）

    # 读取当前活动 collection 名（带旧名回退）
    def _read_active_collection_name(self) -> str:
        """Read the active collection pointer, falling back to the legacy name."""
        if not self.manifest_path.exists():             # 无清单文件
            return self.collection_name                 # 用当前配置名
        try:                                            # 尝试解析
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))  # 读清单
            name = manifest.get("collection_name")      # 取 collection 名
            prefix = f"{self.collection_name}__v_"      # 期望的前缀
            if not isinstance(name, str) or not name.startswith(prefix):  # 校验
                raise ValueError("invalid active collection name")  # 命名不合格
            self._active_manifest = manifest            # 缓存清单
            return name                                 # 返回活动名
        except Exception as exc:                        # 解析失败
            raise RuntimeError(f"索引清单损坏: {self.manifest_path}: {exc}") from exc  # 抛错

    # 打开指定 collection
    def _open_collection(self, name: str):
        if name == self.collection_name and not self.manifest_path.exists():  # 首次且无清单
            return self.db.get_or_create_collection(name)   # 直接创建或获取
        try:                                            # 尝试获取
            return self.db.get_collection(name)         # 获取已有 collection
        except Exception as exc:                        # 不存在
            if name == self.collection_name:            # 若是配置名
                raise                                   # 直接抛错
            logger.warning("active Chroma collection 不存在，将回退并重建: %s (%s)", name, exc)  # 告警
            self._manifest_recovery_required = True     # 标记需恢复
            return self.db.get_or_create_collection(self.collection_name)  # 回退到配置名

    # 检测 active snapshot 是否使用了不同的索引策略
    def _manifest_needs_rebuild(self) -> bool:
        """检测 active snapshot 是否使用了不同的索引策略。"""
        if not self.manifest_path.exists():             # 无清单
            return False                                # 无需重建
        manifest = self._active_manifest or {}          # 取清单
        return (                                        # 任一策略不匹配则需重建
            manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION      # schema 版本不同
            or manifest.get("embedding_model") != settings.EMBEDDING_MODEL # 模型不同
            or manifest.get("chunk_size") != CHUNK_SIZE                    # 块大小不同
            or manifest.get("chunk_overlap") != CHUNK_OVERLAP              # 重叠不同
        )

    # 发布构建完成的 collection（原子替换清单指针）
    def _activate_collection(self, collection_name: str, index, vector_store, storage_context) -> None:
        """Publish a fully-built collection by atomically replacing its pointer."""
        payload = {                                     # 构造清单数据
            "schema_version": MANIFEST_SCHEMA_VERSION,  # 版本
            "collection_name": collection_name,         # 活动 collection 名
            "embedding_model": settings.EMBEDDING_MODEL,  # 模型
            "chunk_size": CHUNK_SIZE,                   # 块大小
            "chunk_overlap": CHUNK_OVERLAP,             # 重叠
        }
        temp_manifest = self.manifest_path.with_name(   # 创建临时清单路径
            f"{self.manifest_path.name}.{uuid4().hex}.tmp"  # 加临时后缀
        )
        try:                                            # 尝试原子替换
            with temp_manifest.open("w", encoding="utf-8") as handle:  # 写临时文件
                json.dump(payload, handle, ensure_ascii=False, indent=2)  # 序列化清单
                handle.flush()                          # 刷新缓冲区
                os.fsync(handle.fileno())               # 落盘
            os.replace(temp_manifest, self.manifest_path)  # 原子替换正式清单
        except Exception:                               # 写失败
            temp_manifest.unlink(missing_ok=True)       # 清理临时文件
            raise                                       # 抛错

        self.chroma_collection = vector_store.client    # 更新 collection
        self.vector_store = vector_store                # 更新向量存储
        self.storage_context = storage_context          # 更新存储上下文
        self.index = index                              # 更新索引
        self.active_collection_name = collection_name   # 更新活动名
        self._active_manifest = payload                 # 更新清单缓存
        self._manifest_recovery_required = False        # 清除恢复标记

    # 检测是否需要从旧版 UUID collection 迁移
    def _legacy_needs_migration(self) -> bool:
        """Detect an old UUID-based collection that has no active manifest."""
        if self.manifest_path.exists() or not self.chroma_collection.count():  # 有清单或空
            return False                                # 无需迁移
        try:                                            # 尝试检查 ids
            ids = self.chroma_collection.get(include=[]).get("ids", [])  # 取所有 id
            return bool(ids) and not all(":chunk:" in str(item) for item in ids)  # 旧版 id 判定
        except Exception:                               # 检查失败
            # A collection that cannot be inspected should be rebuilt so the
            # active pointer is established before serving requests.
            logger.warning("无法检查旧 Chroma collection，触发一次迁移重建", exc_info=True)  # 告警
            return True                                 # 视为需迁移

    # 按读取器类型创建对应 reader 实例
    def _create_reader(self):
        if self.reader_kind == "drone":                 # drone 售后库
            return DroneMarkdownReader()                # 提升 frontmatter 身份字段
        return ObsidianMarkdownReader()                 # obsidian 原库保持原行为

    # 与 drone manifest.json 对账（仅告警，不阻塞索引）
    def _reconcile_manifest(self, documents) -> None:
        """比对实际入库文档与 manifest.json 登记，漂移只记 warning。

        manifest 仅作质量对账清单而非强约束：清单滞后不应阻塞索引构建。
        """
        if self.reader_kind != "drone":                 # 仅 drone 库有 manifest 对账
            return
        manifest_path = self.data_dir / "manifest.json"  # 登记清单路径
        if not manifest_path.exists():                  # 缺清单
            logger.warning("drone 知识库缺少 manifest.json，跳过对账: %s", self.data_dir)  # 告警
            return
        try:                                            # 尝试解析清单
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:                               # 解析失败
            logger.warning("drone manifest.json 解析失败，跳过对账", exc_info=True)  # 告警
            return
        listed = {                                      # 清单登记的文档 id 集合
            str(entry.get("document_id"))
            for entry in manifest.get("documents", [])
            if isinstance(entry, dict) and entry.get("document_id")
        }
        indexed = {                                     # 实际入库的文档 id 集合
            str(doc.metadata.get("document_id"))
            for doc in documents
            if doc.metadata.get("document_id")
        }
        missing = listed - indexed                      # 登记了但未入库
        extra = indexed - listed                        # 入库了但未登记
        if missing:                                     # 漂移告警（截断展示前 10 个）
            logger.warning("manifest 对账：登记但未入库 %d 篇，如 %s", len(missing), sorted(missing)[:10])
        if extra:
            logger.warning("manifest 对账：入库但未登记 %d 篇，如 %s", len(extra), sorted(extra)[:10])
        if not missing and not extra:                   # 完全一致
            logger.info("manifest 对账一致：%d 篇", len(listed))

    # 构建索引
    def build(self):
        reader = self._create_reader()                  # 按类型创建读取器
        documents_by_title = {}                         # 按去重键保存文档
        recursive = self.reader_kind == "drone"         # drone 库递归子目录，obsidian 保持顶层
        for md_file in iter_kb_markdown_files(self.data_dir, recursive=recursive):  # 遍历 Markdown
            try:                                        # 尝试解析
                body = frontmatter.load(md_file).content.strip()  # 取正文并去空白
            except Exception:                           # 解析失败
                logger.warning("跳过无法解析的 Markdown: %s", md_file.name, exc_info=True)  # 告警
                continue                                # 跳过该文件
            if len(body) < MIN_BODY_CHARS:              # 正文过短
                logger.info("跳过过短/疑似损坏的 Markdown: %s (%d 字符)", md_file.name, len(body))  # 记录
                continue                                # 跳过
            loaded = reader.load_data(file_path=md_file)  # 加载文档
            for document in loaded:                     # 遍历文档
                title = str(document.metadata.get("title") or md_file.stem)  # 取标题
                if self.reader_kind == "drone":         # drone 库：以知识库 document_id 去重
                    # 避免归一化标题误合并不同文档；document_id 缺失时回退文件名
                    dedup_key = str(document.metadata.get("document_id") or md_file.name)
                else:                                   # obsidian 库：保持标题归一化去重
                    dedup_key = re.sub(r"\s+", "", title).casefold()  # 标题键归一化（去空小写）
                previous = documents_by_title.get(dedup_key)  # 查已有
                if previous is None or len(document.get_content()) > len(previous.get_content()):  # 保留更长版本
                    documents_by_title[dedup_key] = document  # 覆盖

        documents = list(documents_by_title.values())   # 转为文档列表

        if not documents:                               # 无有效文档
            raise ValueError(f"知识库为空，未找到可索引的 Markdown 文档: {self.data_dir}")  # 抛错

        self._reconcile_manifest(documents)             # drone 库与 manifest 对账（仅告警）

        # Build into an isolated collection.  Chroma's ``add`` operation
        # appends records, and clearing the active collection first would make
        # a failed embedding call take the live index offline.
        candidate_name = f"{self.collection_name}__v_{uuid4().hex}"  # 候选 collection 名
        candidate_collection = self.db.get_or_create_collection(candidate_name)  # 创建候选
        candidate_store = ChromaVectorStore(chroma_collection=candidate_collection)  # 候选存储
        candidate_context = StorageContext.from_defaults(vector_store=candidate_store)  # 候选上下文
        try:                                            # 构建候选索引
            candidate_index = VectorStoreIndex.from_documents(  # 从文档建索引
                documents,                              # 文档
                storage_context=candidate_context,      # 存储上下文
                show_progress=True,                     # 显示进度
            )
            self._activate_collection(                  # 构建成功后发布
                candidate_name, candidate_index, candidate_store, candidate_context
            )
        except Exception:                               # 构建失败
            # The active pointer and collection remain untouched.  Remove only
            # the incomplete candidate so a later rebuild does not accumulate
            # failed snapshots.
            try:                                        # 清理候选
                self.db.delete_collection(candidate_name)  # 删除候选 collection
            except Exception:                           # 清理失败
                logger.warning("清理失败的候选 Chroma collection 失败: %s", candidate_name, exc_info=True)  # 告警
            raise                                       # 抛出原异常

    # 加载或构建索引
    def load_or_build(self):
        """加载已有索引；若 collection 为空或加载失败则重建。

        原实现缺陷：from_vector_store 对空 collection 不报错，
        导致知识库目录缺失/为空时静默加载空索引，所有检索返回空。
        """
        existing_count = self.chroma_collection.count() # 取现有记录数
        if self._manifest_recovery_required or self._manifest_needs_rebuild():  # 需恢复或策略变化
            logger.info("active manifest 与当前索引策略不一致，触发 rebuild")   # 记录
            self.build()                                # 重建
            return
        if existing_count == 0:                         # collection 为空
            # 空索引，必须 rebuild
            logger.info(f"Chroma collection 为空（count=0），触发 rebuild")  # 记录
            self.build()                                # 重建
            return
        if self._legacy_needs_migration():              # 需旧版迁移
            logger.info("检测到旧版 UUID Chroma collection，迁移到版本化 collection")  # 记录
            self.build()                                # 重建
            return
        try:                                            # 尝试加载现有索引
            self.index = VectorStoreIndex.from_vector_store(  # 从向量存储加载
                self.vector_store,                      # 向量存储
                storage_context=self.storage_context,   # 存储上下文
            )
            self.active_collection_name = self.chroma_collection.name  # 记录活动名
        except Exception as e:                          # 加载失败
            logger.warning(f"加载已有索引失败（{e}），触发 rebuild")  # 告警
            self.build()                                # 重建

    # 获取检索器
    def get_retriever(self):
        return RAGRetriever(self.index, top_k=3)        # 返回 top_k=3 的检索器


# 按全局配置解析知识库 profile 并创建索引器（main.lifespan 等入口共用）
def create_profiled_indexer(persist_dir: str | None = None) -> Indexer:
    """依据 KB_PROFILE（或旧变量显式覆盖）解析数据源，创建对应读取器的索引器。

    drone profile → data/drone + drone_kb + DroneMarkdownReader；
    obsidian / 旧变量覆盖 → 原数据目录 + 原 collection + ObsidianMarkdownReader。
    """
    profile = resolve_kb_profile()                  # 解析生效 profile
    logger.info(
        "知识库 profile=%s data_dir=%s collection=%s reader=%s",
        profile.profile, profile.data_dir, profile.collection_name, profile.reader,
    )
    return Indexer(                                 # 创建索引器
        data_dir=str(profile.data_dir),             # profile 解析出的数据目录
        persist_dir=persist_dir or settings.CHROMA_PERSIST_DIR,  # 持久化目录
        collection_name=profile.collection_name,    # profile 对应 collection
        reader=profile.reader,                      # profile 对应读取器
    )