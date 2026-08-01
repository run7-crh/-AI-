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
