# backend/app/extensions.py
"""FastAPI 扩展实例的单一来源，避免 main.py 与 api 模块循环导入。

P1-10: limiter 由 main.py 注册到 app.state，由 api 模块装饰器引用。
"""
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# 测试环境通过 SLOWAPI_ENABLED=false 禁用（避免单 IP 触发限速影响测试）
_limiter_enabled = os.environ.get("SLOWAPI_ENABLED", "true").lower() != "false"
limiter = Limiter(key_func=get_remote_address, enabled=_limiter_enabled)
