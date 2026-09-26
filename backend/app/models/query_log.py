# backend/app/models/query_log.py
"""用户请求全链路日志的 Pydantic 模型。

第 1 阶段：诊断路由错误、检索失败、延迟异常。
写入时机：chat 接口 finally 块一次性 INSERT（不在节点内部写入）。

字段约定：
- retrieved_doc_ids / judge_log / models_used / token_usage 均存 JSON 字符串
- has_source：0/1，标识 final_answer 是否含 [来源：] 或【来源：】标注
- error：NULL 表示正常，否则存异常类型+信息
- token_usage_json：本轮预留 NULL（call_llm 未采集 usage），P2 阶段填充
"""
# 导入类型标注：Optional（可空）
from typing import Optional
# 导入 pydantic 的模型基类与字段校验工具
from pydantic import BaseModel, Field


# 定义写入 query_log 表的入参模型
class QueryLogCreate(BaseModel):
    """写入 query_log 表的入参模型。"""

    id: str                                       # 日志 id
    conversation_id: str                          # 会话 id
    user_id: Optional[str] = None
    user_label: Optional[str] = None              # 提问者标识（可选）
    raw_query: str                                # 用户原始问题
    rewritten_query: Optional[str] = None         # 改写后的查询（可选）
    route_path: Optional[str] = None              # 路由路径（可选）
    rewrite_count: int = 0                        # 改写次数
    retrieved_doc_ids: Optional[str] = None       # 检索到的文档 ID（JSON 数组字符串）
    avg_reranker_score: Optional[float] = None    # 重排平均分（可选）
    judge_log_json: Optional[str] = None          # 判断过程日志（JSON 数组字符串）
    final_answer: Optional[str] = None            # 最终回答（可选）
    answer_length: int = 0                        # 回答长度
    has_source: int = 0                           # 是否含来源标注（0/1）
    models_used_json: Optional[str] = None        # 用到的模型（JSON 对象字符串）
    token_usage_json: Optional[str] = None        # token 用量（本轮 NULL，字段预留）
    fault_key: Optional[str] = None               # 阶段 2: 故障标识"机型__故障类型"（排查失败计数用，可空）
    safety_flag: Optional[bool] = None            # 后端安全判断结果
    safety_level: Optional[str] = None            # 安全等级
    safety_situation: Optional[str] = None        # 设备状态
    escalation_required: Optional[bool] = None   # 是否建议人工升级
    intent: Optional[str] = None                  # 售后意图
    metadata_constraints: Optional[dict] = None   # 检索元数据约束
    document_type_priority: Optional[list[str]] = None  # 文档类型优先级
    recommended_action: Optional[str] = None      # 阶段 4: 业务决策 answer/followup/create_ticket/escalate
    diagnosis_json: Optional[str] = None          # 阶段 4: 结构化诊断（JSON 字符串，可空）
    latency_ms: Optional[int] = None              # 处理延迟毫秒数（可选）
    error: Optional[str] = None                   # 异常描述（NULL 表示正常）
    created_at: str                               # 创建时间


# 定义查询 query_log 表的返回模型
class QueryLogRecord(BaseModel):
    """查询 query_log 表的返回模型（含全部字段）。"""

    id: str                                       # 日志 id
    conversation_id: str                          # 会话 id
    user_id: Optional[str] = None
    user_label: Optional[str] = None              # 提问者标识（可选）
    raw_query: str                                # 用户原始问题
    rewritten_query: Optional[str] = None         # 改写后的查询（可选）
    route_path: Optional[str] = None              # 路由路径（可选）
    rewrite_count: int = 0                        # 改写次数
    retrieved_doc_ids: Optional[str] = None       # 检索到的文档 ID（JSON 数组字符串）
    avg_reranker_score: Optional[float] = None    # 重排平均分（可选）
    judge_log_json: Optional[str] = None          # 判断过程日志（JSON 数组字符串）
    final_answer: Optional[str] = None            # 最终回答（可选）
    answer_length: int = 0                        # 回答长度
    has_source: int = 0                           # 是否含来源标注（0/1）
    models_used_json: Optional[str] = None        # 用到的模型（JSON 对象字符串）
    token_usage_json: Optional[str] = None        # token 用量（可选）
    fault_key: Optional[str] = None               # 阶段 2: 故障标识（可空）
    safety_flag: Optional[bool] = None
    safety_level: Optional[str] = None
    safety_situation: Optional[str] = None
    escalation_required: Optional[bool] = None
    intent: Optional[str] = None
    metadata_constraints: Optional[dict] = None
    document_type_priority: Optional[list[str]] = None
    recommended_action: Optional[str] = None      # 阶段 4: 业务决策
    diagnosis_json: Optional[str] = None          # 阶段 4: 结构化诊断 JSON
    latency_ms: Optional[int] = None              # 处理延迟毫秒数（可选）
    error: Optional[str] = None                   # 异常描述（NULL 表示正常）
    created_at: str                               # 创建时间
