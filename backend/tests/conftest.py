# backend/tests/conftest.py
import os
import tempfile
import pytest

# P1-10: 测试环境禁用 slowapi 限速（避免单 IP 触发 429 影响测试）
os.environ["SLOWAPI_ENABLED"] = "false"


@pytest.fixture(autouse=True, scope="function")
def set_test_sqlite_path():
    """每个测试用独立临时 DB，避免污染。"""
    db_path = tempfile.mktemp(suffix=".db")
    os.environ["TEST_SQLITE_PATH"] = db_path
    yield
    if os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except PermissionError:
            pass  # Windows 文件锁


@pytest.fixture(autouse=True, scope="function")
def _clear_llm_cache():
    """P1-10: 每个测试前清空 ChatOpenAI + TavilyClient 实例缓存，避免 mock 污染。

    call_llm 按 (model, temperature) 缓存 ChatOpenAI 实例，
    tavily_search 用模块级单例 TavilyClient，
    若不清空，前一个测试 mock 的实例会被后续测试复用，导致 patch 失效。
    """
    from app.graph import tools
    tools._llm_cache.clear()
    # P1-10: 重置 TavilyClient 单例
    tools._tavily_client = None
    yield
    tools._llm_cache.clear()
    tools._tavily_client = None
