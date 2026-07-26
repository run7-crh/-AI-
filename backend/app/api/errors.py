# backend/app/api/errors.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# 错误码映射（来自设计文档 7.6 节）
ERROR_MESSAGES = {
    "AuthenticationError": "AI 服务认证失败，请检查 API Key 配置",
    "RateLimitError": "AI 服务调用频率过高，请稍后重试",
    "APIConnectionError": "无法连接到 AI 服务",
    "Timeout": "AI 服务响应超时",
    "ChromaError": "知识库检索失败，可能是索引损坏",
    "EmbeddingError": "向量化服务调用失败",
    "RerankerError": "重排服务调用失败",
    "TavilyError": "联网搜索服务调用失败",
    "OperationalError": "数据库操作失败",
    "ValidationError": "请求参数无效",
}

ERROR_STATUS_CODE = {
    "AuthenticationError": 503,
    "RateLimitError": 429,
    "APIConnectionError": 502,
    "Timeout": 504,
    "ValidationError": 422,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )
