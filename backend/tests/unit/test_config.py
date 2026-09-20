import os
from app.config import Settings

def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    s = Settings()
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
