import os
from pathlib import Path
import pytest
from app.config import Settings

def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    s = Settings(_env_file=None)
    assert s.DEEPSEEK_API_KEY == "sk-test"
    assert s.TAVILY_API_KEY == "tvly-test"
    assert s.MODEL_FLASH == "deepseek-chat"
    assert s.MODEL_PRO_REASON == "deepseek-reasoner"
    assert s.EMBEDDING_MODEL == "bge-large-zh-v1.5"
    assert s.CORS_ORIGINS == ["http://localhost:5173", "http://localhost:4173"]
    assert s.AUTH_ADMIN_USERNAME == "admin"
    assert s.AUTH_ADMIN_PASSWORD == ""
    assert s.AUTH_COOKIE_NAME == "agent_session"
    assert s.AUTH_SESSION_TTL_SECONDS == 604800
    assert s.AUTH_COOKIE_SECURE is False
    assert s.AUTH_PASSWORD_MIN_LENGTH == 8
    assert s.AUTH_PASSWORD_MAX_LENGTH == 128
    assert s.KB_IMPORT_MAX_FILE_BYTES == 10485760
    assert s.KB_IMPORT_MAX_FILES == 20
    assert s.LOG_DIR.endswith("backend\\data\\logs") or s.LOG_DIR.endswith("backend/data/logs")


def test_embedding_model_short_name_is_resolved_to_bge_namespace():
    from app.rag.embedding import _resolve_model_name

    assert _resolve_model_name("bge-large-zh-v1.5") == "BAAI/bge-large-zh-v1.5"
    assert _resolve_model_name("custom/model") == "custom/model"


# ---------------------------------------------------------------------------
# 阶段 1：知识库 profile 解析（resolve_kb_profile）
# ---------------------------------------------------------------------------

def _fresh_settings(monkeypatch, **env) -> Settings:
    """构造脱离真实 .env 的 Settings 实例并替换模块级 settings，供 profile 解析测试。"""
    import app.config as config
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    s = Settings(_env_file=None)
    monkeypatch.setattr(config, "settings", s)
    return s


def test_resolve_kb_profile_defaults_to_drone(monkeypatch):
    import app.config as config
    s = _fresh_settings(monkeypatch, KB_PROFILE=None, KB_DATA_DIR=None, CHROMA_COLLECTION_NAME=None)
    profile = config.resolve_kb_profile()
    assert profile.profile == "drone"
    assert profile.reader == "drone"
    assert profile.collection_name == "drone_kb"
    assert profile.data_dir == Path(s.DRONE_KB_DATA_DIR)
    assert profile.data_dir.name == "drone"


def test_resolve_kb_profile_obsidian_switch(monkeypatch):
    import app.config as config
    _fresh_settings(monkeypatch, KB_PROFILE="obsidian", KB_DATA_DIR=None, CHROMA_COLLECTION_NAME=None)
    profile = config.resolve_kb_profile()
    assert profile.profile == "obsidian"
    assert profile.reader == "obsidian"
    assert profile.collection_name == "obsidian_kb"
    assert profile.data_dir == Path(config.settings.KB_DATA_DIR)
    assert profile.data_dir.name == "raw"


def test_resolve_kb_profile_legacy_env_override_wins(monkeypatch):
    """显式设置 KB_DATA_DIR 时旧口径完全生效（向后兼容既有部署）。"""
    import app.config as config
    _fresh_settings(monkeypatch, KB_PROFILE="obsidian", KB_DATA_DIR="D:/custom/kb", CHROMA_COLLECTION_NAME=None)
    profile = config.resolve_kb_profile()
    assert profile.profile == "custom"
    assert profile.reader == "obsidian"
    assert profile.data_dir == Path("D:/custom/kb")
    assert profile.collection_name == "obsidian_kb"


def test_resolve_kb_profile_rejects_unknown_profile(monkeypatch):
    import app.config as config
    _fresh_settings(monkeypatch, KB_PROFILE="bogus", KB_DATA_DIR=None)
    with pytest.raises(ValueError, match="KB_PROFILE"):
        config.resolve_kb_profile()
