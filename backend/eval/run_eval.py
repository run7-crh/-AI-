"""RAG Agent 评估脚本。

用法：
    cd backend
    python eval/run_eval.py                    # 全量评估
    python eval/run_eval.py --limit 5          # 只跑前 5 题（快速验证）
    python eval/run_eval.py --id q001          # 只跑指定题

输出：
    1. 控制台打印汇总报告
    2. backend/eval/reports/report_YYYYMMDD_HHMMSS.json（带时间戳，可重复运行）

依赖：
    httpx + asgi_lifespan（与 tests/integration 一致）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 确保 backend 在 sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# 时区（与项目约定一致）
_TZ = timezone(timedelta(hours=8))


# 评估约定：
# - expected_documents 是检索评估的唯一真值来源（兼容旧数据集的 expected_source）。
# - 关键词只作为可解释的 lexical coverage 辅助信号，不再冒充答案相关性。
# - 没有 reference_answer 的题不计算 answer relevance；没有标注文档的题不计算
#   Recall/MRR。报告会显式给出分母和 applicable 数量，避免把“非空”当成 Recall。
def _expected_documents(question: dict) -> list[str]:
    docs = question.get("expected_documents")
    if docs is None:
        source = question.get("expected_source")
        docs = [source] if source else []
    if isinstance(docs, str):
        docs = [docs]
    return [str(doc).strip() for doc in docs if str(doc).strip()]


def _document_id(source: object) -> str:
    """从 SSE source/evidence 兼容提取文档标识。"""
    if isinstance(source, dict):
        return str(
            # 评估数据集以可读文件名为标签；document_id 是稳定 hash，
            # 仅作为没有 source 时的兼容回退。
            source.get("source")
            or source.get("file_name")
            or source.get("title")
            or source.get("url")
            or source.get("document_id")
            or ""
        ).strip()
    return str(source or "").strip()


def _normalize_document_label(value: str) -> str:
    """按文件名比较证据标签，兼容绝对路径和 Windows 分隔符。"""
    normalized = str(value or "").replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1].casefold()


def _document_label_variants(value: str) -> set[str]:
    """Return filename and stem labels used by evidence and answer citations."""
    label = _normalize_document_label(value)
    if not label:
        return set()
    variants = {label}
    if "." in label:
        variants.add(label.rsplit(".", 1)[0])
    return variants


def _citation_text(answer: str) -> str:
    """Extract explicit ``来源`` marker contents from a generated answer."""
    matches = re.findall(r"(?:\[|【)\s*来源[:：]\s*([^\]】\n（(]+)", answer or "")
    return " ".join(matches).casefold()


def _is_local_evidence(source: object) -> bool:
    """判断 SSE evidence 是否属于本地索引，兼容旧版本地 source 字段。"""
    if not isinstance(source, dict) or source.get("is_error"):
        return False
    source_type = source.get("source_type")
    if source_type is not None:
        return source_type == "local"
    # 旧响应未带 source_type；带 URL 或 URL 形态的 source 视为 Web。
    source_value = str(source.get("source") or "").strip().lower()
    return not source.get("url") and not source_value.startswith(("http://", "https://"))


def _retrieval_metrics(expected: list[str], retrieved: list[str]) -> dict:
    """按文档级标注计算 Recall@K 和 reciprocal rank。"""
    expected_set = {_normalize_document_label(doc) for doc in expected if doc}
    ranked = []
    seen = set()
    for doc in retrieved:
        normalized = _normalize_document_label(doc)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ranked.append(doc)
    first_rank = next(
        (i + 1 for i, doc in enumerate(ranked) if _normalize_document_label(doc) in expected_set),
        None,
    )

    def recall_at(k: int) -> float:
        if not expected_set:
            return 0.0
        retrieved_set = {_normalize_document_label(doc) for doc in ranked[:k]}
        return len(expected_set.intersection(retrieved_set)) / len(expected_set)

    def ndcg_at(k: int) -> float:
        """二值文档相关性的 nDCG@K。"""
        if not expected_set:
            return 0.0
        gains = [
            1.0 if _normalize_document_label(doc) in expected_set else 0.0
            for doc in ranked[:k]
        ]
        dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
        ideal_hits = min(len(expected_set), k)
        idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
        return dcg / idcg if idcg else 0.0

    return {
        "applicable": bool(expected_set),
        "expected_documents": expected,
        "retrieved_documents": ranked,
        "hit_at_1": bool(first_rank and first_rank <= 1),
        "hit_at_3": bool(first_rank and first_rank <= 3),
        "hit_at_5": bool(first_rank and first_rank <= 5),
        "recall_at_1": recall_at(1),
        "recall_at_3": recall_at(3),
        "recall_at_5": recall_at(5),
        "ndcg_at_1": ndcg_at(1),
        "ndcg_at_3": ndcg_at(3),
        "ndcg_at_5": ndcg_at(5),
        "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
        "first_relevant_rank": first_rank,
    }


def _tokenize(text: str) -> list[str]:
    """轻量 token 化，仅用于可复现的 lexical F1，不声称语义正确。"""
    import re

    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", (text or "").lower())


def _token_f1(prediction: str, reference: str) -> float | None:
    if not reference:
        return None
    pred_tokens = _tokenize(prediction)
    ref_tokens = _tokenize(reference)
    if not pred_tokens or not ref_tokens:
        return 0.0
    pred_counts = {}
    ref_counts = {}
    for token in pred_tokens:
        pred_counts[token] = pred_counts.get(token, 0) + 1
    for token in ref_tokens:
        ref_counts[token] = ref_counts.get(token, 0) + 1
    overlap = sum(min(count, ref_counts.get(token, 0)) for token, count in pred_counts.items())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def _classification_accuracy(results: list[dict], field: str) -> float | None:
    """Return exact accuracy for an explicitly labelled structured field.

    Missing expected or actual values are excluded from the denominator.  This
    keeps legacy/unlabelled records compatible and prevents guessing from text.
    """
    expected_key = f"expected_{field}"
    actual_key = f"actual_{field}"
    applicable = [r for r in results if r.get(expected_key) is not None and r.get(actual_key) is not None]
    if not applicable:
        return None
    return sum(r.get(expected_key) == r.get(actual_key) for r in applicable) / len(applicable)


def _safety_recall(results: list[dict]) -> float | None:
    """Recall of explicitly labelled high-risk cases only."""
    applicable = [r for r in results if r.get("expected_safety_level") == "high"]
    if not applicable:
        return None
    return sum(
        r.get("actual_safety_level") == "high" or r.get("actual_safety_flag") is True
        for r in applicable
    ) / len(applicable)


def _cross_model_contamination_count(results: list[dict]) -> int:
    """Count retrieved local evidence whose explicit model conflicts with gold.

    Generic ``all`` metadata is safe and therefore excluded.  Records without
    an expected model are not judged because there is no reliable reference.
    """
    count = 0
    for result in results:
        expected = str(result.get("expected_product_model") or "").strip().lower()
        if not expected:
            continue
        for source in result.get("retrieved_sources", []) or []:
            if not isinstance(source, dict) or source.get("source_type") not in (None, "local"):
                continue
            model = str(source.get("product_model") or "").strip().lower()
            if model and model not in ("all", expected):
                count += 1
    return count


async def stream_chat(client: AsyncClient, conv_id: str, question: str) -> dict:
    """调 /api/chat，流式读取 SSE，返回 route_path/final_answer/sources/has_source/latency。

    Returns:
        {
            "route_path": str | None,
            "final_answer": str,
            "retrieved_doc_ids": list[str],   # 从 meta.sources 提取（兼容旧字段）
            "retrieved_sources": list[dict],  # 原始 evidence，供文档/引用评估
            "has_source": bool,                # 答案是否含 [来源：] 标注
            "latency_ms": int,
            "error": str | None,
        }
    """
    t0 = time.time()
    final_answer = ""
    route_path = None
    retrieved_doc_ids = []
    retrieved_sources = []
    has_source = False
    has_hallucination = None
    intent = None
    product_model = None
    document_type_priority = None
    metadata_constraints = None
    safety_flag = None
    safety_level = None
    escalation_required = None
    # 阶段 7: Agent 业务决策与结构化诊断（旧后端无这些 meta 字段时保持 None）
    recommended_action = None
    agent_ticket = None
    information_gaps = None
    diagnosis = None
    error = None

    try:
        async with client.stream(
            "POST",
            "/api/chat",
            json={"conversation_id": conv_id, "message": question, "user_label": "eval"},
        ) as resp:
            if resp.status_code != 200:
                error = f"HTTP {resp.status_code}"
                return {
                    "route_path": None, "final_answer": "",
                    "retrieved_doc_ids": [], "retrieved_sources": [], "has_hallucination": None,
                    "intent": None, "product_model": None, "document_type_priority": None,
                    "metadata_constraints": None, "safety_flag": None, "safety_level": None,
                    "escalation_required": None,
                    "recommended_action": None, "agent_ticket": None,
                    "information_gaps": None, "diagnosis": None,
                    "has_source": False,
                    "latency_ms": int((time.time() - t0) * 1000), "error": error,
                }

            buffer = ""
            async for line in resp.aiter_lines():
                if not line:
                    continue
                # SSE 格式：data: {...}\n\n（aiter_lines 已按行返回）
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")
                    if etype == "token":
                        final_answer += event.get("data", "")
                    elif etype == "final":
                        # 新版 API 发送 canonical final 事件；使用它覆盖 token
                        # 聚合，避免流式重试/重复 token 造成答案重复。
                        final_data = event.get("data", "")
                        if isinstance(final_data, dict):
                            final_data = final_data.get(
                                "answer",
                                final_data.get("final_answer", final_data.get("content", "")),
                            )
                        if isinstance(final_data, str):
                            final_answer = final_data
                    elif etype == "meta":
                        meta = event.get("data", {})
                        route_path = meta.get("route_path")
                        if not final_answer and isinstance(meta.get("final_answer"), str):
                            final_answer = meta["final_answer"]
                        sources = meta.get("sources", []) or []
                        retrieved_sources = [s for s in sources if isinstance(s, dict)]
                        retrieved_doc_ids = [
                            _document_id(source)
                            for source in sources
                            if _is_local_evidence(source) and _document_id(source)
                        ]
                        intent = meta.get("intent")
                        metadata_constraints = meta.get("metadata_constraints")
                        if isinstance(metadata_constraints, dict):
                            product_model = metadata_constraints.get("product_model")
                        if not product_model:
                            source_models = {
                                str(source.get("product_model")).strip().lower()
                                for source in retrieved_sources
                                if source.get("product_model") and str(source.get("product_model")).strip().lower() != "all"
                            }
                            if len(source_models) == 1:
                                product_model = next(iter(source_models))
                        document_type_priority = meta.get("document_type_priority")
                        safety_flag = meta.get("safety_flag")
                        safety_level = meta.get("safety_level")
                        escalation_required = meta.get("escalation_required")
                        # 阶段 7: 业务决策/自动建单/缺口/结构化诊断
                        recommended_action = meta.get("recommended_action")
                        agent_ticket = meta.get("agent_ticket")
                        information_gaps = meta.get("information_gaps")
                        diagnosis = meta.get("diagnosis")
                        judge_log = meta.get("judge_log") or []
                        for judge in reversed(judge_log):
                            raw = judge.get("raw_output", {}) if isinstance(judge, dict) else {}
                            if isinstance(raw, dict) and "has_hallucination" in raw:
                                value = raw["has_hallucination"]
                                has_hallucination = value if isinstance(value, bool) else None
                                # 最新一次质量判定无效时，不回退到更早的结果。
                                break
                    elif etype == "error":
                        err_data = event.get("data", {})
                        error = err_data.get("message", "未知错误") if isinstance(err_data, dict) else str(err_data)
                    elif etype == "done":
                        break
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    has_source = "[来源：" in final_answer or "【来源：" in final_answer
    return {
        "route_path": route_path,
        "final_answer": final_answer,
        "retrieved_doc_ids": retrieved_doc_ids,
        "retrieved_sources": retrieved_sources,
        "has_hallucination": has_hallucination,
        "intent": intent,
        "product_model": product_model,
        "document_type_priority": document_type_priority,
        "metadata_constraints": metadata_constraints,
        "safety_flag": safety_flag,
        "safety_level": safety_level,
        "escalation_required": escalation_required,
        "recommended_action": recommended_action,
        "agent_ticket": agent_ticket,
        "information_gaps": information_gaps,
        "diagnosis": diagnosis,
        "has_source": has_source,
        "latency_ms": int((time.time() - t0) * 1000),
        "error": error,
    }


def create_conversation(client: AsyncClient) -> str:
    """同步包装：创建会话。实际在 main 中用 await 调用。"""
    # 这里返回 coroutine，由调用方 await
    return client.post("/api/conversations", json={})


async def eval_one(client: AsyncClient, q: dict) -> dict:
    """评估单条问题。每条用独立会话，避免历史污染。"""
    if q.get("multi_turn"):
        # 阶段 7: 追问后第二轮需要跨轮上下文（上一轮 followup + 本轮补充），
        # 单轮 SSE 评估器无法可靠模拟，标记跳过并留待人工/脚本化多轮验证。
        return {
            "id": q["id"], "question": q["question"], "category": q["category"],
            "skipped_multi_turn": True,
        }

    # 创建独立会话
    create_resp = await client.post("/api/conversations", json={})
    conv_id = create_resp.json()["id"]

    # 调 chat
    chat_result = await stream_chat(client, conv_id, q["question"])

    # 判定
    actual_route = chat_result["route_path"]
    expected_routes = q["acceptable_routes"]
    route_correct = actual_route in expected_routes if actual_route else False

    expected_documents = _expected_documents(q)
    retrieval = _retrieval_metrics(expected_documents, chat_result["retrieved_doc_ids"])

    # 关键词只作为显式开启的辅助诊断。自动生成的关键词不能代表答案相关性。
    keywords = q.get("expected_answer_keywords", []) or []
    keyword_coverage = None
    if keywords and q.get("keyword_eval", False):
        matched = sum(
            1 for kw in keywords
            if str(kw).lower() in chat_result["final_answer"].lower()
        )
        keyword_coverage = matched / len(keywords)

    # 没有人工 reference_answer 时，不计算 answer relevance；有标注时使用可复现
    # 的 lexical F1，并在报告中明确它不是 LLM-as-a-judge。
    reference_answer = q.get("reference_answer")
    answer_relevance = _token_f1(chat_result["final_answer"], reference_answer)

    # 检索命中与答案引用分开。``source_correct`` 保留旧字段语义（预期文档
    # 是否出现在检索结果）；``citation_correct`` 才检查答案文本中的文档名。
    retrieval_source_hit = None
    citation_correct = None
    if expected_documents and actual_route in ("local", "decomposition"):
        expected_labels = {
            label
            for doc in expected_documents
            for label in _document_label_variants(doc)
        }
        retrieval_source_hit = any(
            bool(_document_label_variants(doc) & expected_labels)
            for doc in chat_result["retrieved_doc_ids"]
        )
        answer_citations = _citation_text(chat_result["final_answer"])
        citation_correct = any(
            any(label in answer_citations for label in _document_label_variants(doc))
            for doc in expected_documents
        )

    # 旧字段保留为 None，避免把 hit@3/非空结果误称为“检索成功率”。
    # 新调用方请使用 retrieval_hit_at_3 与 retrieval_recall_at_3。
    retrieval_success = None

    # 没有结构化质量事件时无法可靠判断幻觉，使用 None 而不是“没有来源即幻觉”。
    hallucination_suspected = chat_result.get("has_hallucination")

    # ------------------------------------------------------------------
    # 阶段 7: Agent 业务指标（expected_action 为 None 的题不计入 action 分母）
    # ------------------------------------------------------------------
    expected_action = q.get("expected_action")
    expected_auto_ticket = q.get("expected_auto_ticket")
    expected_gaps = q.get("expected_gaps") or []
    actual_action = chat_result.get("recommended_action")
    actual_ticket = chat_result.get("agent_ticket")
    actual_gaps_raw = chat_result.get("information_gaps") or []
    actual_gap_fields = {
        str(gap.get("field", "")).strip()
        for gap in actual_gaps_raw
        if isinstance(gap, dict)
    }
    actual_diagnosis = chat_result.get("diagnosis")

    action_correct = (
        (actual_action == expected_action) if expected_action else None
    )
    ticket_action_correct = (
        (bool(actual_ticket) == bool(expected_auto_ticket))
        if expected_auto_ticket is not None
        else None
    )
    followup_gap_hit = None
    if expected_action == "followup" and expected_gaps:
        followup_gap_hit = (
            sum(1 for field in expected_gaps if field in actual_gap_fields)
            / len(expected_gaps)
        )
    diagnosis_present = actual_diagnosis is not None if actual_route == "local" else None
    diagnosis_citation_validity = None
    if isinstance(actual_diagnosis, dict):
        citations = actual_diagnosis.get("citations") or []
        if citations:
            evidence_ids = {
                str(src.get("id"))
                for src in chat_result.get("retrieved_sources", [])
                if isinstance(src, dict) and src.get("id")
            }
            diagnosis_citation_validity = sum(
                1 for c in citations
                if isinstance(c, dict) and str(c.get("evidence_id") or "") in evidence_ids
            ) / len(citations)
    elif actual_route == "local":
        diagnosis_citation_validity = None  # 无诊断（降级）不参与引用校验均值

    return {
        "id": q["id"],
        "question": q["question"],
        "category": q["category"],
        "difficulty": q["difficulty"],
        "source_type": q.get("source_type", "seed"),
        "expected_routes": expected_routes,
        "expected_source": q.get("expected_source"),
        "expected_documents": expected_documents,
        "gold_status": q.get("gold_status", "legacy"),
        "expected_intent": q.get("expected_intent"),
        "expected_product_model": q.get("expected_product_model"),
        "expected_document_type_priority": q.get("document_type_priority") or q.get("expected_document_type_priority"),
        "expected_safety_level": q.get("expected_safety_level"),
        "expected_escalation": q.get("expected_escalation"),
        "expected_action": expected_action,
        "expected_auto_ticket": expected_auto_ticket,
        "expected_gaps": expected_gaps,
        "actual_action": actual_action,
        "actual_auto_ticket": bool(actual_ticket) if actual_ticket else False,
        "actual_gaps": actual_gaps_raw,
        "action_correct": action_correct,
        "ticket_action_correct": ticket_action_correct,
        "followup_gap_hit": followup_gap_hit,
        "diagnosis_present": diagnosis_present,
        "diagnosis_citation_validity": diagnosis_citation_validity,
        "actual_route": actual_route,
        "actual_intent": chat_result.get("intent"),
        "actual_product_model": chat_result.get("product_model"),
        "actual_document_type_priority": chat_result.get("document_type_priority"),
        "actual_safety_flag": chat_result.get("safety_flag"),
        "actual_safety_level": chat_result.get("safety_level"),
        "actual_escalation": chat_result.get("escalation_required"),
        "route_correct": route_correct,
        "answer_relevant": answer_relevance,
        "answer_relevance": answer_relevance,
        "answer_f1": answer_relevance,
        "keyword_coverage": keyword_coverage,
        "source_correct": retrieval_source_hit,
        "retrieval_source_hit": retrieval_source_hit,
        "citation_correct": citation_correct,
        "retrieval_success": retrieval_success,
        "retrieval_hit_at_3": retrieval["hit_at_3"] if retrieval["applicable"] else None,
        "retrieval_non_empty": bool(chat_result["retrieved_doc_ids"]),
        "retrieval_recall_at_1": retrieval["recall_at_1"] if retrieval["applicable"] else None,
        "retrieval_recall_at_3": retrieval["recall_at_3"] if retrieval["applicable"] else None,
        "retrieval_recall_at_5": retrieval["recall_at_5"] if retrieval["applicable"] else None,
        "retrieval_ndcg_at_1": retrieval["ndcg_at_1"] if retrieval["applicable"] else None,
        "retrieval_ndcg_at_3": retrieval["ndcg_at_3"] if retrieval["applicable"] else None,
        "retrieval_ndcg_at_5": retrieval["ndcg_at_5"] if retrieval["applicable"] else None,
        "retrieval_mrr": retrieval["reciprocal_rank"] if retrieval["applicable"] else None,
        "retrieval_first_relevant_rank": retrieval["first_relevant_rank"],
        "retrieval_metrics": {
            "recall_at_1": retrieval["recall_at_1"] if retrieval["applicable"] else None,
            "recall_at_3": retrieval["recall_at_3"] if retrieval["applicable"] else None,
            "recall_at_5": retrieval["recall_at_5"] if retrieval["applicable"] else None,
            "mrr": retrieval["reciprocal_rank"] if retrieval["applicable"] else None,
            "ndcg_at_1": retrieval["ndcg_at_1"] if retrieval["applicable"] else None,
            "ndcg_at_3": retrieval["ndcg_at_3"] if retrieval["applicable"] else None,
            "ndcg_at_5": retrieval["ndcg_at_5"] if retrieval["applicable"] else None,
        },
        "hallucination_suspected": hallucination_suspected,
        "retrieved_doc_ids": chat_result["retrieved_doc_ids"],
        "retrieved_sources": chat_result.get("retrieved_sources", []),
        "has_source": chat_result["has_source"],
        "final_answer": chat_result["final_answer"],
        "latency_ms": chat_result["latency_ms"],
        "error": chat_result["error"],
    }


def aggregate(results: list[dict]) -> dict:
    """聚合统计。"""
    # 阶段 7: 多轮题（追问后第二轮）单轮评估器无法模拟，单独计数不进任何分母
    skipped_results = [r for r in results if r.get("skipped_multi_turn")]
    results = [r for r in results if not r.get("skipped_multi_turn")]
    total = len(results)

    # 路由准确率：所有题计入分母
    route_correct_count = sum(1 for r in results if r.get("route_correct"))
    route_accuracy = route_correct_count / total if total else 0

    # 答案 lexical F1：只有提供 reference_answer 的题计入分母；没有参考答案时
    # 返回 None，避免把关键词命中率误报为答案相关性。
    relevance_values = [r.get("answer_relevance") for r in results if r.get("answer_relevance") is not None]
    relevance_denom = len(relevance_values)
    answer_relevance = sum(relevance_values) / relevance_denom if relevance_denom else None

    keyword_values = [r.get("keyword_coverage") for r in results if r.get("keyword_coverage") is not None]
    keyword_coverage = sum(keyword_values) / len(keyword_values) if keyword_values else None
    gold_status_counts = {}
    for result in results:
        status = result.get("gold_status", "legacy")
        gold_status_counts[status] = gold_status_counts.get(status, 0) + 1

    # 引用正确率：检查答案中是否出现预期文档名，与检索 Recall 严格分开。
    source_denom = sum(1 for r in results if r.get("citation_correct") is not None)
    source_count = sum(1 for r in results if r.get("citation_correct") is True)
    source_correctness = source_count / source_denom if source_denom else None

    # 旧键 retrieval_success_rate 明确置空；历史实现把非空结果误称为成功率。
    # 检索分母使用真正 applicable 的 Recall@3 结果。
    retrieval_denom = sum(1 for r in results if r.get("retrieval_recall_at_3") is not None)
    retrieval_success_rate = None
    hit_values = [r.get("retrieval_hit_at_3") for r in results if r.get("retrieval_hit_at_3") is not None]
    retrieval_hit_at_3 = sum(hit_values) / len(hit_values) if hit_values else None
    source_hit_values = [r.get("retrieval_source_hit") for r in results if r.get("retrieval_source_hit") is not None]
    retrieval_source_hit_rate = (
        sum(source_hit_values) / len(source_hit_values) if source_hit_values else None
    )
    non_empty_values = [r.get("retrieval_non_empty", bool(r.get("retrieved_doc_ids"))) for r in results]
    retrieval_non_empty_rate = (
        sum(non_empty_values) / len(non_empty_values) if non_empty_values else None
    )

    retrieval_values = {
        key: [r.get(key) for r in results if r.get(key) is not None]
        for key in (
            "retrieval_recall_at_1", "retrieval_recall_at_3", "retrieval_recall_at_5",
            "retrieval_ndcg_at_1", "retrieval_ndcg_at_3", "retrieval_ndcg_at_5",
            "retrieval_mrr",
        )
    }
    retrieval_averages = {
        key: (sum(values) / len(values) if values else None)
        for key, values in retrieval_values.items()
    }

    # 幻觉数
    hallucination_values = [
        r.get("hallucination_suspected")
        for r in results
        if isinstance(r.get("hallucination_suspected"), bool)
    ]
    hallucination_denom = len(hallucination_values)
    hallucination_count = (
        sum(value is True for value in hallucination_values) if hallucination_denom else None
    )
    hallucination_cases = [
        r for r in results if r.get("hallucination_suspected") is True
    ]

    intent_accuracy = _classification_accuracy(results, "intent")
    product_model_accuracy = _classification_accuracy(results, "product_model")
    document_type_priority_accuracy = _classification_accuracy(results, "document_type_priority")
    safety_recall = _safety_recall(results)
    escalation_accuracy = _classification_accuracy(results, "escalation")
    cross_model_contamination_count = _cross_model_contamination_count(results)

    # ------------------------------------------------------------------
    # 阶段 7: Agent 业务指标（分母只含带 gold 标注且可判定的题）
    # ------------------------------------------------------------------
    action_denom = [r for r in results if r.get("action_correct") is not None]
    action_accuracy = (
        sum(1 for r in action_denom if r["action_correct"]) / len(action_denom)
        if action_denom else None
    )
    ticket_denom = [r for r in results if r.get("ticket_action_correct") is not None]
    ticket_action_accuracy = (
        sum(1 for r in ticket_denom if r["ticket_action_correct"]) / len(ticket_denom)
        if ticket_denom else None
    )
    gap_values = [r.get("followup_gap_hit") for r in results if r.get("followup_gap_hit") is not None]
    followup_gap_hit_rate = sum(gap_values) / len(gap_values) if gap_values else None
    diagnosis_denom = [r for r in results if r.get("diagnosis_present") is not None]
    diagnosis_coverage = (
        sum(1 for r in diagnosis_denom if r["diagnosis_present"]) / len(diagnosis_denom)
        if diagnosis_denom else None
    )
    diagnosis_citation_values = [
        r.get("diagnosis_citation_validity")
        for r in results
        if r.get("diagnosis_citation_validity") is not None
    ]
    diagnosis_citation_validity_rate = (
        sum(diagnosis_citation_values) / len(diagnosis_citation_values)
        if diagnosis_citation_values else None
    )

    # 失败案例（路由错误或报错）
    failed_cases = [
        {
            "id": r["id"],
            "reason": "error" if r["error"] else "route_wrong",
            "expected": r["expected_routes"],
            "actual": r["actual_route"],
            "error": r["error"],
        }
        for r in results
        if not r.get("route_correct")
    ]

    # 按类别分组
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {
                "count": 0, "route_correct": 0, "source_correct": 0,
                "source_denom": 0, "hallucination": 0, "hallucination_denom": 0,
                "retrieval_count": 0, "recall_at_3_sum": 0.0,
            }
        categories[cat]["count"] += 1
        if r.get("route_correct"):
            categories[cat]["route_correct"] += 1
        if r.get("citation_correct") is not None:
            categories[cat]["source_denom"] += 1
            if r.get("citation_correct"):
                categories[cat]["source_correct"] += 1
        if r.get("hallucination_suspected") is True:
            categories[cat]["hallucination"] += 1
        if isinstance(r.get("hallucination_suspected"), bool):
            categories[cat]["hallucination_denom"] += 1
        if r.get("retrieval_recall_at_3") is not None:
            categories[cat]["retrieval_count"] += 1
            categories[cat]["recall_at_3_sum"] += r["retrieval_recall_at_3"]

    by_category = {}
    for cat, stats in categories.items():
        by_category[cat] = {
            "count": stats["count"],
            "route_accuracy": stats["route_correct"] / stats["count"] if stats["count"] else 0,
            "source_correctness": stats["source_correct"] / stats["source_denom"] if stats["source_denom"] else None,
            "retrieval_recall_at_3": (
                stats["recall_at_3_sum"] / stats["retrieval_count"]
                if stats["retrieval_count"] else None
            ),
            "hallucination_count": (
                stats["hallucination"] if stats["hallucination_denom"] else None
            ),
            "hallucination_denom": stats["hallucination_denom"],
        }

    # 按难度分组
    difficulties = {}
    for r in results:
        diff = r["difficulty"]
        if diff not in difficulties:
            difficulties[diff] = {"count": 0, "route_correct": 0}
        difficulties[diff]["count"] += 1
        if r["route_correct"]:
            difficulties[diff]["route_correct"] += 1

    by_difficulty = {
        diff: {
            "count": s["count"],
            "route_accuracy": s["route_correct"] / s["count"] if s["count"] else 0,
        }
        for diff, s in difficulties.items()
    }

    inferred_count = gold_status_counts.get("inferred", 0)
    unlabeled_count = gold_status_counts.get("unlabeled", 0)
    warnings = []
    if relevance_denom == 0:
        warnings.append("当前数据集未提供 reference_answer，因此 answer_relevance 不可计算。")
    else:
        warnings.append(f"answer_relevance 使用 {relevance_denom} 条 reference_answer 计算 lexical token F1；不是语义评估。")
    if retrieval_denom:
        warnings.append(f"Recall/MRR 对 {retrieval_denom} 条提供 expected_documents 的题计算。")
    else:
        warnings.append("当前数据集未提供 expected_documents，因此 Recall/MRR 不可计算。")
    if inferred_count:
        warnings.append(f"有 {inferred_count} 条 expected_documents 由主题规则推断（gold_status=inferred），发布指标前应人工复核。")
    if unlabeled_count:
        warnings.append(f"有 {unlabeled_count} 条题未标注文档（gold_status=unlabeled），不进入 Recall/MRR 分母。")
    warnings.append("retrieval_success_rate 是兼容字段，固定为 null；请使用 Recall@K、MRR 或 hit_at_3。")
    if hallucination_denom:
        warnings.append(f"结构化幻觉检查覆盖 {hallucination_denom}/{total} 条；疑似幻觉数仅统计有布尔判定的题。")
    else:
        warnings.append("未配置结构化幻觉标注时，不根据缺少[来源]文本推断幻觉。")

    return {
        "total_questions": total,
        "summary": {
            "route_accuracy": route_accuracy,
            "answer_relevance": answer_relevance,
            "answer_f1": answer_relevance,
            "source_correctness": source_correctness,
            "citation_correctness": source_correctness,
            "retrieval_success_rate": retrieval_success_rate,
            "retrieval_hit_at_3": retrieval_hit_at_3,
            "retrieval_source_hit_rate": retrieval_source_hit_rate,
            "retrieval_non_empty_rate": retrieval_non_empty_rate,
            "retrieval_recall_at_1": retrieval_averages["retrieval_recall_at_1"],
            "retrieval_recall_at_3": retrieval_averages["retrieval_recall_at_3"],
            "retrieval_recall_at_5": retrieval_averages["retrieval_recall_at_5"],
            "retrieval_ndcg_at_1": retrieval_averages["retrieval_ndcg_at_1"],
            "retrieval_ndcg_at_3": retrieval_averages["retrieval_ndcg_at_3"],
            "retrieval_ndcg_at_5": retrieval_averages["retrieval_ndcg_at_5"],
            "retrieval_mrr": retrieval_averages["retrieval_mrr"],
            "keyword_coverage": keyword_coverage,
            "answer_f1_denom": relevance_denom,
            "hallucination_count": hallucination_count,
            "relevance_denom": relevance_denom,
            "source_denom": source_denom,
            "retrieval_denom": retrieval_denom,
            "hallucination_denom": hallucination_denom,
            "hallucination_coverage": hallucination_denom / total if total else None,
            "hallucination_rate": (
                hallucination_count / hallucination_denom
                if hallucination_denom else None
            ),
            "retrieval_gold_status_counts": gold_status_counts,
            "intent_accuracy": intent_accuracy,
            "product_model_accuracy": product_model_accuracy,
            "document_type_priority_accuracy": document_type_priority_accuracy,
            "safety_recall": safety_recall,
            "escalation_accuracy": escalation_accuracy,
            "cross_model_contamination_count": cross_model_contamination_count,
            # 阶段 7: Agent 业务指标
            "action_accuracy": action_accuracy,
            "action_denom": len(action_denom),
            "ticket_action_accuracy": ticket_action_accuracy,
            "ticket_action_denom": len(ticket_denom),
            "followup_gap_hit_rate": followup_gap_hit_rate,
            "followup_gap_denom": len(gap_values),
            "diagnosis_coverage": diagnosis_coverage,
            "diagnosis_denom": len(diagnosis_denom),
            "diagnosis_citation_validity": diagnosis_citation_validity_rate,
            "diagnosis_citation_denom": len(diagnosis_citation_values),
            "skipped_multi_turn": len(skipped_results),
            "skipped_multi_turn_ids": [r["id"] for r in skipped_results],
        },
        "metric_definitions": {
            "route_accuracy": "actual_route 命中 acceptable_routes 的比例",
            "retrieval_recall_at_1": "标注 expected_documents 在前 1 个结果中的文档级 Recall",
            "retrieval_recall_at_3": "标注 expected_documents 在前 3 个结果中的文档级 Recall",
            "retrieval_recall_at_5": "标注 expected_documents 在前 5 个结果中的文档级 Recall",
            "retrieval_ndcg_at_1": "前 1 个结果的二值文档相关性 nDCG",
            "retrieval_ndcg_at_3": "前 3 个结果的二值文档相关性 nDCG",
            "retrieval_ndcg_at_5": "前 5 个结果的二值文档相关性 nDCG",
            "retrieval_mrr": "第一个相关文档排名倒数的平均值",
            "retrieval_hit_at_3": "前 3 个结果中至少命中一个标注文档的比例；不等同于 Recall@3",
            "retrieval_source_hit_rate": "预期文档是否出现在返回结果中的比例；多文档题不等同于完整 Recall",
            "retrieval_success_rate": "deprecated；固定为 null，避免误读历史非空结果指标",
            "source_correctness": "deprecated alias of citation_correctness",
            "citation_correctness": "答案文本明确包含预期文档名的比例；不等同于事实级引用正确性",
            "answer_relevance": "reference_answer 存在时的 lexical token F1；不是语义评估",
            "keyword_coverage": "显式 keyword_eval=true 时的辅助关键词覆盖率，不是答案质量",
            "hallucination_suspected": "仅消费 API 提供的结构化 has_hallucination；缺失时为 null",
            "intent_accuracy": "expected_intent 与 SSE meta.intent 的精确匹配；无完整字段时为 null",
            "product_model_accuracy": "expected_product_model 与 SSE metadata_constraints.product_model 的精确匹配；无可靠机型时为 null",
            "document_type_priority_accuracy": "expected_document_type_priority 与 SSE meta.document_type_priority 的有序列表精确匹配",
            "safety_recall": "expected_safety_level=high 的题中，后端返回 high/true 的比例",
            "escalation_accuracy": "expected_escalation 与 SSE meta.escalation_required 的精确匹配",
            "cross_model_contamination_count": "明确机型题中，返回本地证据的 product_model 与期望机型冲突的条数；all 不计入",
            "action_accuracy": "expected_action 与 SSE meta.recommended_action 的精确匹配（answer/followup/create_ticket/escalate）",
            "ticket_action_accuracy": "expected_auto_ticket 与 meta.agent_ticket 是否出现的精确匹配（含误报与漏报）",
            "followup_gap_hit_rate": "followup 题中，expected_gaps 字段出现在 meta.information_gaps 的平均命中率",
            "diagnosis_coverage": "local 路径题中结构化诊断（meta.diagnosis）产出比例",
            "diagnosis_citation_validity": "diagnosis.citations 中 evidence_id 命中实际证据 id 的平均比例（程序校验）",
            "skipped_multi_turn": "multi_turn=true 的题数，单轮评估器跳过，需人工/脚本多轮验证",
        },
        "warnings": warnings,
        "by_category": by_category,
        "by_difficulty": by_difficulty,
        "failed_cases": failed_cases,
        "hallucination_cases": [
            {
                "id": r["id"],
                "question": r["question"],
                "route": r["actual_route"],
                "answer_preview": r["final_answer"][:100],
            }
            for r in hallucination_cases
        ],
        "results": results,
    }


def print_summary(report: dict, dataset_version: str) -> None:
    """控制台打印汇总报告。"""
    now = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")
    s = report["summary"]

    def format_metric(value: float | None, percentage: bool = False) -> str:
        if value is None:
            return "N/A"
        return f"{value * 100:.1f}%" if percentage else f"{value:.3f}"

    print("\n" + "=" * 60)


    print(f"=== RAG Agent 评估报告 ===")
    print(f"时间: {now}")
    print(f"数据集: v{dataset_version} ({report['total_questions']} 题)")
    print("=" * 60)

    print("\n【整体指标】")
    print(f"路由准确率:        {s['route_accuracy']*100:.1f}% ({int(s['route_accuracy']*report['total_questions'])}/{report['total_questions']})")
    if s['answer_relevance'] is None:
        print("答案相关性:        N/A（数据集未提供 reference_answer）")
    else:
        print(f"答案 lexical F1:   {s['answer_relevance']*100:.1f}% ({int(s['answer_relevance']*s['relevance_denom'])}/{s['relevance_denom']})")
    if s['source_correctness'] is None:
        print("引用正确率:        N/A（无可验证的文档名引用）")
    else:
        source_pct = s['source_correctness'] * 100
        print(f"引用正确率:        {source_pct:.1f}% ({int(s['source_correctness']*s['source_denom'])}/{s['source_denom']})")
    if s.get('retrieval_recall_at_3') is None:
        print("检索 Recall@3:     N/A（数据集未提供 expected_documents）")
    else:
        recall_scores = " / ".join(format_metric(s.get(f"retrieval_recall_at_{k}"), True) for k in (1, 3, 5))
        ndcg_scores = " / ".join(format_metric(s.get(f"retrieval_ndcg_at_{k}")) for k in (1, 3, 5))
        print(f"检索 Recall@1/3/5: {recall_scores}")
        print(f"检索 nDCG@1/3/5:   {ndcg_scores}")
        print(f"检索 MRR:          {format_metric(s.get('retrieval_mrr'))}（Hit@3: {format_metric(s.get('retrieval_hit_at_3'), True)}）")
    if s.get('keyword_coverage') is not None:
        print(f"关键词覆盖率:       {s['keyword_coverage']*100:.1f}%（辅助诊断）")
    hallucination_display = "N/A" if s.get("hallucination_count") is None else str(s["hallucination_count"])
    print(f"疑似幻觉数:        {hallucination_display}")
    print(f"意图准确率:        {format_metric(s.get('intent_accuracy'), True)}")
    print(f"机型准确率:        {format_metric(s.get('product_model_accuracy'), True)}")
    print(f"文档优先级准确率:  {format_metric(s.get('document_type_priority_accuracy'), True)}")
    print(f"安全召回率:        {format_metric(s.get('safety_recall'), True)}")
    print(f"升级准确率:        {format_metric(s.get('escalation_accuracy'), True)}")
    print(f"跨机型污染条数:    {s.get('cross_model_contamination_count', 0)}")

    print("\n【按类别】")
    for cat, stats in report["by_category"].items():
        route_pct = stats["route_accuracy"] * 100
        line = f"{cat:<18} ({stats['count']:>2}题) 路由 {route_pct:.1f}%"
        if stats["source_correctness"] is not None:
            line += f" | 引用 {stats['source_correctness']*100:.1f}%"
        if stats.get("hallucination_count"):
            line += f" | 幻觉 {stats['hallucination_count']}"
        print(line)

    print("\n【按难度】")
    for diff in ["easy", "medium", "hard"]:
        if diff in report["by_difficulty"]:
            stats = report["by_difficulty"][diff]
            print(f"{diff:<8} ({stats['count']:>2}题) 路由 {stats['route_accuracy']*100:.1f}%")

    if report["failed_cases"]:
        print("\n【失败案例】")
        for fc in report["failed_cases"]:
            reason = "报错" if fc["reason"] == "error" else "路由错误"
            err_info = f" [{fc['error']}]" if fc["error"] else ""
            print(f"  {fc['id']} 期望 {fc['expected']} 实际 {fc['actual']}{err_info}  |  {reason}")

    if report["hallucination_cases"]:
        print("\n【疑似幻觉】")
        for hc in report["hallucination_cases"]:
            print(f"  {hc['id']} route={hc['route']} 结构化质量检查判定疑似幻觉 | {hc['question'][:30]}...")

    print("\n" + "=" * 60)


def validate_dataset(dataset: dict) -> dict:
    """Offline-only schema validation; never calls the API, GPU or network."""
    questions = dataset.get("questions") if isinstance(dataset, dict) else None
    if not isinstance(questions, list) or not questions:
        raise ValueError("dataset.questions 不能为空")
    required = {
        "question", "category", "difficulty", "expected_route", "acceptable_routes",
        "expected_documents", "expected_product_model", "expected_intent",
        "expected_safety_level", "expected_escalation", "gold_status",
    }
    missing = [item.get("id", "<unknown>") for item in questions if not required <= item.keys()]
    if missing:
        raise ValueError(f"评估题缺少结构化字段: {missing}")
    return {
        "version": dataset.get("version"),
        "question_count": len(questions),
        "categories": sorted({item["category"] for item in questions}),
        "gold_status_counts": {
            status: sum(item.get("gold_status") == status for item in questions)
            for status in sorted({item.get("gold_status") for item in questions})
        },
        "external_evaluation": "not_run",
    }


async def main():
    parser = argparse.ArgumentParser(description="RAG Agent 评估脚本")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题（快速验证）")
    parser.add_argument("--id", type=str, default=None, help="只跑指定题 ID（如 q001）")
    parser.add_argument("--offline", action="store_true", help="只验证评估集结构，不启动 API/GPU/联网服务")
    args = parser.parse_args()

    # 加载数据集
    dataset_path = Path(__file__).parent / "dataset.json"
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    if args.offline:
        print(json.dumps(validate_dataset(dataset), ensure_ascii=False, indent=2))
        return

    # 仅在真正执行在线评估时加载 Web/API 依赖。离线模式不触发应用、模型或网络。
    from httpx import AsyncClient, ASGITransport
    from asgi_lifespan import LifespanManager
    from app.main import app

    questions = dataset["questions"]
    if args.id:
        questions = [q for q in questions if q["id"] == args.id]
        if not questions:
            print(f"未找到 ID={args.id} 的问题")
            sys.exit(1)
    elif args.limit:
        questions = questions[: args.limit]

    print(f"开始评估：{len(questions)} 题")
    print(f"数据集版本: v{dataset['version']}")

    # 启动 app 并评估
    results = []
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 阶段 7 修复：评估脚本构建于认证功能（09-20）之前，从未真正跑通在线
            # 评估——/api/conversations 现在要求登录 Cookie。注册/登录评估用户。
            register = await client.post(
                "/api/auth/register",
                json={"username": "eval-bot", "password": "Eval-pass-12345"},
            )
            if register.status_code not in (201, 409):
                print(f"评估用户创建失败: {register.status_code} {register.text}")
                sys.exit(1)
            login = await client.post(
                "/api/auth/login",
                json={"username": "eval-bot", "password": "Eval-pass-12345"},
            )
            if login.status_code != 200:
                print(f"评估用户登录失败: {login.status_code} {login.text}")
                sys.exit(1)

            for i, q in enumerate(questions, 1):
                print(f"\r[{i}/{len(questions)}] 评估 {q['id']} {q['question'][:30]}...", end="", flush=True)
                result = await eval_one(client, q)
                results.append(result)
                if result.get("skipped_multi_turn"):
                    print(f"\n  ⏭ 跳过多轮题 {q['id']}（需人工/脚本多轮验证）")
                    continue
                # 实时打印异常
                if result.get("error"):
                    print(f"\n  ✗ 错误: {result['error']}")
                else:
                    route_ok = "✓" if result["route_correct"] else "✗"
                    print(f"\r[{i}/{len(questions)}] {route_ok} {q['id']} route={result['actual_route']} latency={result['latency_ms']}ms")

    # 聚合
    report = aggregate(results)

    # 加元数据
    now = datetime.now(_TZ)
    report_id = now.strftime("eval_%Y%m%d_%H%M%S")
    report_full = {
        "report_id": report_id,
        "timestamp": now.isoformat(),
        "dataset_version": dataset["version"],
        **report,
    }

    # 保存报告（带时间戳）
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_file = reports_dir / f"report_{now.strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_full, f, ensure_ascii=False, indent=2)

    # 控制台打印
    print_summary(report_full, dataset["version"])
    print(f"报告已保存: {report_file}")


if __name__ == "__main__":
    asyncio.run(main())
