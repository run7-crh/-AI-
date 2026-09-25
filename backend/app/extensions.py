# backend/app/extensions.py
"""FastAPI 扩展实例的单一来源，避免 main.py 与 api 模块循环导入。

P1-10: limiter 由 main.py 注册到 app.state，由 api 模块装饰器引用。
"""
# 导入 os，用于读取环境变量控制限速开关
import os
# 导入 slowapi 的 Limiter，用于接口速率限制
from slowapi import Limiter
# 导入获取客户端 IP 的工具函数，作为限速的键来源
from slowapi.util import get_remote_address

# 测试环境通过 SLOWAPI_ENABLED=false 禁用（避免单 IP 触发限速影响测试）
_limiter_enabled = os.environ.get("SLOWAPI_ENABLED", "true").lower() != "false"  # 读环境变量判断是否启用
limiter = Limiter(key_func=get_remote_address, enabled=_limiter_enabled)  # 创建限速器（按客户端 IP 限流）