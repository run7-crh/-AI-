from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM (DeepSeek)
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # Embedding & Reranker (华为云 MaaS)
    HUAWEI_API_KEY: str
    HUAWEI_BASE_URL: str = "https://maas.cn-north-4.myhuaweicloud.com"
    EMBEDDING_MODEL: str = "bge-large-zh-v1.5"
    RERANKER_MODEL: str = "bge-reranker-v2-m3"

    # Tavily
    TAVILY_API_KEY: str

    # 知识库
    KB_DATA_DIR: str = r"D:\Project\Self-RAG-Agent\data\raw"
    CHROMA_PERSIST_DIR: str = "backend/data/chroma"

    # SQLite
    SQLITE_PATH: str = "backend/data/agent.db"

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
