# backend/app/models/query_log.py
"""用户请求全链路日志的 Pydantic 模型。

第 1 阶段：诊断路由错误、检索失败、延迟异常。
写入时机：chat 接口 finally 块一次性 INSERT（不在节点内部写入）。

字段约定：
- retrieved_doc_ids / judge_log / models_used / token_usage 均存 JSON 字符串
- has_source：0/1，标识 final_answer 是否含 [来源：] 标注
- error：NULL 表示正常，否则存异常类型+信息
- token_usage_json：本轮预留 NULL（call_llm 未采集 usage），P2 阶段填充
"""
from typing import Optional
from pydantic import BaseModel, Field


class QueryLogCreate(BaseModel):
    """写入 query_log 表的入参模型。"""

    id: str
    conversation_id: str
    user_label: Optional[str] = None
    raw_query: str
    rewritten_query: Optional[str] = None
    route_path: Optional[str] = None
    rewrite_count: int = 0
    retrieved_doc_ids: Optional[str] = None  # JSON 数组字符串
    avg_reranker_score: Optional[float] = None
    judge_log_json: Optional[str] = None  # JSON 数组字符串
    final_answer: Optional[str] = None
    answer_length: int = 0
    has_source: int = 0
    models_used_json: Optional[str] = None  # JSON 对象字符串
    token_usage_json: Optional[str] = None  # 本轮 NULL，字段预留
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    created_at: str


class QueryLogRecord(BaseModel):
    """查询 query_log 表的返回模型（含全部字段）。"""

    id: str
    conversation_id: str
    user_label: Optional[str] = None
    raw_query: str
    rewritten_query: Optional[str] = None
    route_path: Optional[str] = None
    rewrite_count: int = 0
    retrieved_doc_ids: Optional[str] = None
    avg_reranker_score: Optional[float] = None
    judge_log_json: Optional[str] = None
    final_answer: Optional[str] = None
    answer_length: int = 0
    has_source: int = 0
    models_used_json: Optional[str] = None
    token_usage_json: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    created_at: str
