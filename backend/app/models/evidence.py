# backend/app/models/evidence.py
"""Shared evidence representation used by local RAG and web search.

Keeping one small, serialisable shape for both providers makes source handling
in prompts, traces and API responses predictable.  The helpers intentionally
return plain dictionaries so existing state and JSON serialisation continue to
work without a conversion layer.
"""

from __future__ import annotations               # 允许后续版本的前向类型标注语法

# 导入 sha256，用于生成确定性的证据 id
from hashlib import sha256
# 导入类型标注：Any（任意）、Literal（限定取值）、TypedDict（键值类型字典）
from typing import Any, Literal, TypedDict


# 定义证据的数据结构（TypedDict，字段可缺省 total=False）
class Evidence(TypedDict, total=False):
    """A piece of evidence consumed by answer generation."""

    id: str                                      # 证据 id
    source_type: Literal["local", "web", "attachment"]  # 来源类型
    title: str                                   # 标题
    content: str                                 # 内容
    url: str | None                              # 原文链接（可空）
    source: str                                  # 来源信息
    document_id: str | None                      # 所属文档 id（可空）
    chunk_id: str | None                         # 块 id（可空）
    score: float | None                          # 相关性分数（可空）
    is_error: bool                               # 是否表示提供方失败而非证据
    # 阶段 1（drone 知识库）：本地检索时从向量 metadata 透出的售后身份字段。
    # 全部可空，web 证据与旧 collection 不携带，保持向后兼容。
    document_type: str | None                    # 文档类型：product/technical/troubleshooting/sop/safety/case
    product_model: str | None                    # 适用机型（all=跨机型通用）
    component: str | None                        # 涉及部件
    fault_type: str | None                       # 故障类型（troubleshooting/case 专属）
    data_type: str | None                        # 数据性质：factual / synthetic（模拟案例）
    source_id: str | None                        # 来源登记号（逗号分隔，指向 sources.md）


# 定义生成确定性证据 id 的函数
def evidence_id(*parts: str) -> str:
    """Return a deterministic, short identifier for evidence content."""

    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()  # 拼接各段并 SHA-256 摘要
    return digest[:16]                           # 截取前 16 位作为短 id


# 定义将证据格式化为 LLM prompt 上下文的函数
def format_evidence_context(items: list[dict] | str | None) -> str:
    """Format evidence for an LLM prompt while retaining source identity.

    ``str`` is accepted for compatibility with old persisted state and tests;
    new callers should pass a list of :class:`Evidence` dictionaries.
    """

    if not items:                                # 无任何来源
        return "（无可用来源）"                  # 返回占位提示
    if isinstance(items, str):                   # 兼容旧状态：直接是字符串
        return items                             # 原样返回

    parts: list[str] = []                        # 存放格式化后的片段
    for index, item in enumerate(items, start=1):  # 带序号遍历来源项
        if not isinstance(item, dict):           # 非字典项
            parts.append(f"[{index}] {item}")    # 直接按字符串输出
            continue
        if item.get("is_error"):                 # 是失败标记项
            continue                             # 跳过
        content = str(item.get("content", "")).strip()  # 取内容并去空白
        if not content:                          # 内容为空
            continue                             # 跳过
        title = item.get("title") or item.get("source") or item.get("url") or "未知来源"  # 推导标题
        url = item.get("url")                    # 取链接
        source = item.get("source")              # 取来源
        # Local citations should use the real file name (the value already
        # exposed by the API/evaluation scripts); web citations use title and
        # retain URL for a clickable, verifiable reference.
        display = source if item.get("source_type") == "local" and source else title  # 本地用文件名，其余用标题
        source_line = f"【来源：{display}】"     # 拼来源行
        if source and source != display and source != url:  # 另有独立文件字段
            source_line += f"（文件：{source}）" # 追加文件来源
        if display != title and item.get("source_type") == "local" and title:  # 本地且标题不同
            source_line += f"（标题：{title}）"  # 追加标题
        if url:                                  # 有链接
            source_line += f"（URL：{url}）"     # 追加链接以便可点击核验
        trace_fields = []
        for field in ("document_id", "source_id", "product_model"):
            value = item.get(field)
            if value:
                trace_fields.append(f"{field}={value}")
        if trace_fields:
            source_line += f"（{'; '.join(trace_fields)}）"
        if item.get("data_type") == "synthetic":
            source_line += "（模拟案例）"
        parts.append(f"[{index}] {source_line}\n{content}")  # 拼整个人类可读条目
    return "\n\n".join(parts) or "（无可用来源）"  # 片段间空行拼接，空则兜底占位


# 定义判断某条目是否为错误标记的函数
def is_evidence_error(item: Any) -> bool:
    """Whether an item represents a provider failure rather than evidence."""

    return isinstance(item, dict) and bool(item.get("is_error"))  # 字典且带 is_error 即为失败项
