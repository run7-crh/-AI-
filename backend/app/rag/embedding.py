# backend/app/rag/embedding.py
"""LlamaIndex embedding 模型配置：本地 HuggingFace BGE。

原设计用华为云 MaaS 的 bge-large-zh-v1.5，但账号下未提供 embedding 模型权限，
改为本地 HuggingFace 推理（同模型 `BAAI/bge-large-zh-v1.5`，输出维度 1024）。

首次运行会从 HuggingFace Hub 下载模型（约 1.3GB），后续从本地缓存加载。
"""
# 导入日志模块
import logging
# 从 llama_index.core 导入全局 Settings，用于设定全局 embedding 模型
from llama_index.core import Settings
# 导入 HuggingFace 本地 embedding 组件
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# 导入全局配置
from app.config import settings

# 获取当前模块日志器
logger = logging.getLogger(__name__)

# bge-large-zh-v1.5 输出维度
EMBED_DIM = 1024                # 向量维度常量
# HuggingFace 模型 ID（默认配置可写短名，兼容旧 .env）
DEFAULT_HF_NAMESPACE = "BAAI/"  # HuggingFace 命名空间前缀


# 定义模型名解析函数：把配置的短名补全为完整 HuggingFace model id
def _resolve_model_name(configured: str) -> str:
    configured = (configured or "").strip()  # 去空并去首尾空白
    if not configured:                       # 配置为空
        return "BAAI/bge-large-zh-v1.5"      # 用默认模型
    return configured if "/" in configured else f"{DEFAULT_HF_NAMESPACE}{configured}"  # 含/直接用，否则补前缀


# 定义 embedding 配置函数
def configure_embedding() -> None:
    """配置 LlamaIndex 全局 embedding 模型为本地 HuggingFace BGE。

    必须在 Indexer.build() / VectorStoreIndex.from_documents() 之前调用。
    首次调用会触发模型下载（约 1.3GB）。

    P2-2: 移除模块导入时的自动调用，改为由 Indexer.__init__ 显式调用，
    避免任何 import（含测试 mock）触发模型加载。
    """
    model_name = _resolve_model_name(settings.EMBEDDING_MODEL)  # 解析完整模型名
    embed_model = HuggingFaceEmbedding(   # 创建本地 embedding 模型
        model_name=model_name,            # 模型名
        cache_folder=settings.EMBEDDING_CACHE_DIR,  # 本地缓存目录
    )
    Settings.embed_model = embed_model    # 写入 LlamaIndex 全局设置
    logger.info(                          # 记录配置日志
        f"Embedding 配置完成: model={model_name}, "
        f"embed_dim={EMBED_DIM}, backend=local-huggingface, "
        f"cache_dir={settings.EMBEDDING_CACHE_DIR}"
    )