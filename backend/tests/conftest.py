# backend/tests/conftest.py
import os
import tempfile
import pytest


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
