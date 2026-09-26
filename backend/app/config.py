# backend/app/config.py
# 导入 dataclass，用于定义知识库 profile 解析结果
from dataclasses import dataclass
# 导入 Path，用于计算项目根目录
from pathlib import Path

# 导入 pydantic-settings 的基类与配置模型，用于从环境变量/.env 加载配置
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/app/config.py → backend/app → backend → 项目根）
# 定位到项目根，供后续相对路径拼接使用
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# 定义应用配置类，继承 pydantic BaseSettings 从环境变量/.env 读取
class Settings(BaseSettings):
    AUTH_ADMIN_USERNAME: str = "admin"
    AUTH_ADMIN_PASSWORD: str = ""
    AUTH_COOKIE_NAME: str = "agent_session"
    AUTH_SESSION_TTL_SECONDS: int = 604800
    AUTH_COOKIE_SECURE: bool = False
    AUTH_PASSWORD_MIN_LENGTH: int = 8
    AUTH_PASSWORD_MAX_LENGTH: int = 128

    # LLM (DeepSeek)
    DEEPSEEK_API_KEY: str                       # DeepSeek API 密钥（必填，来自环境变量/.env）
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"  # DeepSeek 接口地址（默认官方）

    # Embedding & Reranker（本地 BGE，华为云 MaaS 配置已废弃）
    EMBEDDING_MODEL: str = "bge-large-zh-v1.5"  # 本地文本向量化模型
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"  # 本地重排模型

    # Tavily
    TAVILY_API_KEY: str                         # Tavily 联网搜索 API 密钥（必填）

    # 知识库（相对项目根目录，避免硬编码绝对路径污染他人环境）
    KB_DATA_DIR: str = str(_PROJECT_ROOT / "data" / "raw")  # 原始知识库 Markdown 目录
    CHROMA_PERSIST_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "chroma")  # Chroma 持久化目录
    # P2-12: Chroma collection 名称可配置，默认 obsidian_kb（向后兼容）
    CHROMA_COLLECTION_NAME: str = "obsidian_kb"  # 向量集合名称

    # 知识库 profile（阶段 1：无人机售后知识库接入）
    # - "drone"（默认）：使用 data/drone 无人机售后知识库 + 独立 Chroma collection，
    #   与原 AI 学习知识库在向量层完全隔离，避免互相污染检索召回
    # - "obsidian"：回退到原 AI 学习知识库 data/raw + obsidian_kb
    # 兼容规则：显式设置环境变量 KB_DATA_DIR 时优先级最高，完全沿用旧口径
    KB_PROFILE: str = "drone"
    DRONE_KB_DATA_DIR: str = str(_PROJECT_ROOT / "data" / "drone")  # 无人机售后知识库目录
    DRONE_CHROMA_COLLECTION_NAME: str = "drone_kb"  # 无人机库独立 collection 名

    # 模型缓存目录（显式锚定到项目内，避免 LlamaIndex/sentence-transformers
    # 回退到 Windows 默认 %LOCALAPPDATA% 造成 C 盘冗余下载）
    EMBEDDING_CACHE_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "llama_cache")  # embedding 模型缓存目录
    RERANKER_CACHE_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "hf_home" / "hub")  # reranker 模型缓存目录

    # SQLite
    SQLITE_PATH: str = str(_PROJECT_ROOT / "backend" / "data" / "agent.db")  # SQLite 数据库文件路径

    # Temporary user attachments.  These files are never indexed into Chroma.
    ATTACHMENT_STORAGE_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "attachments")
    ATTACHMENT_MAX_FILE_BYTES: int = 25 * 1024 * 1024
    ATTACHMENT_MAX_FILES_PER_UPLOAD: int = 5
    ATTACHMENT_MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024
    ATTACHMENT_MAX_SESSION_BYTES: int = 50 * 1024 * 1024
    ATTACHMENT_MAX_CONTEXT_CHARS: int = 400_000
    ATTACHMENT_TTL_HOURS: int = 24
    ATTACHMENT_MAX_FILENAME_LENGTH: int = 180

    KB_IMPORT_MAX_FILE_BYTES: int = 10 * 1024 * 1024
    KB_IMPORT_MAX_FILES: int = 20
    LOG_DIR: str = str(_PROJECT_ROOT / "backend" / "data" / "logs")

    # 知识图谱产物（graph_builder 全量重建生成，GET /api/graph 直接读此文件）
    KG_JSON_PATH: str = str(_PROJECT_ROOT / "backend" / "data" / "kg.json")  # 知识图谱产物文件路径

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:4173"]  # 允许跨域的来源列表

    # 模型映射
    MODEL_FLASH: str = "deepseek-chat"          # "flash" 角色对应的实际模型
    MODEL_PRO_CHAT: str = "deepseek-chat"       # "pro-chat" 角色对应的实际模型
    MODEL_PRO_REASON: str = "deepseek-reasoner" # "pro-reason" 角色对应的推理模型

    # Agent 售后升级能力开关（阶段 3-6 增量改造，docs/agent/target_architecture.md §17 回滚方案）
    # 默认 False 保持既有行为；全部测试与验收通过后，由 Final Review 置 True 启用。
    AGENT_FOLLOWUP_ENABLED: bool = False        # 信息不足时主动追问（ask_followup 节点）
    AGENT_AUTO_TICKET_ENABLED: bool = False     # Agent 决策后自动创建工单草稿（chat.py 胶水）
    ADMIN_AI_ANALYSIS_ENABLED: bool = False     # 管理端工单 AI 分析端点

    # pydantic-settings 配置：加载 .env、UTF-8 编码、忽略未声明字段
    model_config = SettingsConfigDict(
        env_file=".env",                        # 从 .env 文件读取
        env_file_encoding="utf-8",              # .env 采用 UTF-8
        extra="ignore",                         # 忽略多余的环境变量
    )


# 实例化全局配置，供各模块 import 使用
settings = Settings()


# 定义知识库 profile 解析结果：数据目录 + collection 名 + 读取器类型
@dataclass(frozen=True)
class KBProfile:
    profile: str            # "drone" / "obsidian" / "custom"（旧变量显式覆盖）
    data_dir: Path          # 知识库 Markdown 根目录
    collection_name: str    # Chroma collection 名
    reader: str             # 读取器类型："obsidian" / "drone"


# 解析当前生效的知识库 profile（数据目录、collection 名、读取器类型）
def resolve_kb_profile() -> KBProfile:
    """按优先级解析生效知识库，供 indexer / graph_builder 共用：

    1. 显式设置 KB_DATA_DIR → 旧口径完全生效（兼容既有部署，profile 标记 custom）
    2. KB_PROFILE=obsidian → 原 AI 学习知识库 data/raw + obsidian_kb
    3. 默认 KB_PROFILE=drone → 无人机售后知识库 data/drone + drone_kb
    """
    # model_fields_set 记录"被环境变量/.env 显式赋值"的字段，用于旧变量兼容判断
    if "KB_DATA_DIR" in settings.model_fields_set:
        return KBProfile(
            profile="custom",
            data_dir=Path(settings.KB_DATA_DIR),
            collection_name=settings.CHROMA_COLLECTION_NAME,
            reader="obsidian",
        )
    profile = settings.KB_PROFILE.strip().lower()
    if profile == "obsidian":
        return KBProfile("obsidian", Path(settings.KB_DATA_DIR), settings.CHROMA_COLLECTION_NAME, "obsidian")
    if profile == "drone":
        return KBProfile("drone", Path(settings.DRONE_KB_DATA_DIR), settings.DRONE_CHROMA_COLLECTION_NAME, "drone")
    raise ValueError(f"未知 KB_PROFILE: {settings.KB_PROFILE!r}（可选 obsidian / drone）")
