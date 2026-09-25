# backend/app/api/errors.py
# 导入 FastAPI 的 FastAPI 应用类与请求对象
from fastapi import FastAPI, Request
# 导入 JSON 响应类，用于返回错误信息
from fastapi.responses import JSONResponse

# 错误码映射（来自设计文档 7.6 节）
ERROR_MESSAGES = {
    "AuthenticationError": "AI 服务认证失败，请检查 API Key 配置",  # 认证失败
    "RateLimitError": "AI 服务调用频率过高，请稍后重试",            # 限流
    "APIConnectionError": "无法连接到 AI 服务",                      # 连接失败
    "Timeout": "AI 服务响应超时",                                    # 超时
    "ChromaError": "知识库检索失败，可能是索引损坏",                  # 向量库检索失败
    "EmbeddingError": "向量化服务调用失败",                          # 向量化失败
    "RerankerError": "重排服务调用失败",                             # 重排失败
    "TavilyError": "联网搜索服务调用失败",                           # 联网搜索失败
    "OperationalError": "数据库操作失败",                            # 数据库失败
    "ValidationError": "请求参数无效",                               # 参数无效
}


# 定义全局异常处理器注册函数
def register_error_handlers(app: FastAPI) -> None:
    # 注册 ValueError 异常的统一处理
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(                        # 返回 400 错误
            status_code=400,                        # HTTP 400
            content={"error": str(exc)},            # 携带错误详情
        )
