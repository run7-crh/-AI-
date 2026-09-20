from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/app/config.py → backend/app → backend → 项目根）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    AUTH_ADMIN_USERNAME: str = "admin"
    AUTH_ADMIN_PASSWORD: str = ""
    AUTH_COOKIE_NAME: str = "agent_session"
    AUTH_SESSION_TTL_SECONDS: int = 604800
    AUTH_COOKIE_SECURE: bool = False
    AUTH_PASSWORD_MIN_LENGTH: int = 8
    AUTH_PASSWORD_MAX_LENGTH: int = 128

    # LLM (DeepSeek)
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # Embedding & Reranker（本地 BGE，华为云 MaaS 配置已废弃）
    EMBEDDING_MODEL: str = "bge-large-zh-v1.5"
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # Tavily
    TAVILY_API_KEY: str

    # 知识库（相对项目根目录，避免硬编码绝对路径污染他人环境）
    KB_DATA_DIR: str = str(_PROJECT_ROOT / "data" / "raw")
    CHROMA_PERSIST_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "chroma")
    # P2-12: Chroma collection 名称可配置，默认 obsidian_kb（向后兼容）
    CHROMA_COLLECTION_NAME: str = "obsidian_kb"

    # 模型缓存目录（显式锚定到项目内，避免 LlamaIndex/sentence-transformers
    # 回退到 Windows 默认 %LOCALAPPDATA% 造成 C 盘冗余下载）
    EMBEDDING_CACHE_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "llama_cache")
    RERANKER_CACHE_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "hf_home" / "hub")

    # SQLite
    SQLITE_PATH: str = str(_PROJECT_ROOT / "backend" / "data" / "agent.db")

    KB_IMPORT_MAX_FILE_BYTES: int = 10 * 1024 * 1024
    KB_IMPORT_MAX_FILES: int = 20
    LOG_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "logs")

    # 知识图谱产物（graph_builder 全量重建生成，GET /api/graph 直接读此文件）
    KG_JSON_PATH: str = str(_PROJECT_ROOT / "backend" / "data" / "kg.json")

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # 模型映射
    MODEL_FLASH: str = "deepseek-chat"
    MODEL_PRO_CHAT: str = "deepseek-chat"
    MODEL_PRO_REASON: str = "deepseek-reasoner"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
