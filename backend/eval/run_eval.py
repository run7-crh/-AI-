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
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 确保 backend 在 sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from httpx import AsyncClient, ASGITransport
from asgi_lifespan import LifespanManager

from app.main import app

# 时区（与项目约定一致）
_TZ = timezone(timedelta(hours=8))


async def stream_chat(client: AsyncClient, conv_id: str, question: str) -> dict:
    """调 /api/chat，流式读取 SSE，返回 route_path/final_answer/sources/has_source/latency。

    Returns:
        {
            "route_path": str | None,
            "final_answer": str,
            "retrieved_doc_ids": list[str],   # 从 meta.sources 提取
            "has_source": bool,                # 答案是否含 [来源：] 标注
            "latency_ms": int,
            "error": str | None,
        }
    """
    t0 = time.time()
    final_answer = ""
    route_path = None
    retrieved_doc_ids = []
    has_source = False
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
                    "retrieved_doc_ids": [], "has_source": False,
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
                    elif etype == "meta":
                        meta = event.get("data", {})
                        route_path = meta.get("route_path")
                        sources = meta.get("sources", []) or []
                        retrieved_doc_ids = [s.get("source") for s in sources if s.get("source")]
                    elif etype == "error":
                        err_data = event.get("data", {})
                        error = err_data.get("message", "未知错误") if isinstance(err_data, dict) else str(err_data)
                    elif etype == "done":
                        # 等待后端 finally 块完成 query_log 落库（客户端立即断开会导致落库被取消）
                        await asyncio.sleep(2)
                        break
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    has_source = "[来源：" in final_answer
    return {
        "route_path": route_path,
        "final_answer": final_answer,
        "retrieved_doc_ids": retrieved_doc_ids,
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
    # 创建独立会话
    create_resp = await client.post("/api/conversations", json={})
    conv_id = create_resp.json()["id"]

    # 调 chat
    chat_result = await stream_chat(client, conv_id, q["question"])

    # 判定
    actual_route = chat_result["route_path"]
    expected_routes = q["acceptable_routes"]
    route_correct = actual_route in expected_routes if actual_route else False

    # answer_relevance: any（包含任一关键词即算相关）
    keywords = q.get("expected_answer_keywords", []) or []
    if keywords:
        answer_relevant = any(kw in chat_result["final_answer"] for kw in keywords)
    else:
        # 无关键词的题（如 knowledge_missing/hallucination_test 部分题）跳过此指标
        answer_relevant = None

    # source_correctness: 仅 local/decomposition 路径判定，expected_source 为 null 跳过
    expected_source = q.get("expected_source")
    if actual_route in ("local", "decomposition") and expected_source:
        source_correct = expected_source in chat_result["retrieved_doc_ids"]
    else:
        source_correct = None  # 跳过

    # retrieval_success: 仅 local 路径判定
    if actual_route == "local":
        retrieval_success = len(chat_result["retrieved_doc_ids"]) > 0
    else:
        retrieval_success = None  # 跳过

    # hallucination_suspected: 走了 local/decomposition 但答案无 [来源：] 标注
    hallucination_suspected = (
        actual_route in ("local", "decomposition") and not chat_result["has_source"]
    )

    return {
        "id": q["id"],
        "question": q["question"],
        "category": q["category"],
        "difficulty": q["difficulty"],
        "source_type": q.get("source_type", "seed"),
        "expected_routes": expected_routes,
        "expected_source": expected_source,
        "actual_route": actual_route,
        "route_correct": route_correct,
        "answer_relevant": answer_relevant,
        "source_correct": source_correct,
        "retrieval_success": retrieval_success,
        "hallucination_suspected": hallucination_suspected,
        "retrieved_doc_ids": chat_result["retrieved_doc_ids"],
        "has_source": chat_result["has_source"],
        "final_answer": chat_result["final_answer"],
        "latency_ms": chat_result["latency_ms"],
        "error": chat_result["error"],
    }


def aggregate(results: list[dict]) -> dict:
    """聚合统计。"""
    total = len(results)

    # 路由准确率：所有题计入分母
    route_correct_count = sum(1 for r in results if r["route_correct"])
    route_accuracy = route_correct_count / total if total else 0

    # 答案相关性：仅有关键词的题计入分母（answer_relevant 非 None）
    relevance_denom = sum(1 for r in results if r["answer_relevant"] is not None)
    relevance_count = sum(1 for r in results if r["answer_relevant"] is True)
    answer_relevance = relevance_count / relevance_denom if relevance_denom else 0

    # 引用正确率：仅 local/decomposition 且有 expected_source 的题计入分母
    source_denom = sum(1 for r in results if r["source_correct"] is not None)
    source_count = sum(1 for r in results if r["source_correct"] is True)
    source_correctness = source_count / source_denom if source_denom else 0

    # 检索成功率：仅 local 路径计入分母
    retrieval_denom = sum(1 for r in results if r["retrieval_success"] is not None)
    retrieval_count = sum(1 for r in results if r["retrieval_success"] is True)
    retrieval_success_rate = retrieval_count / retrieval_denom if retrieval_denom else 0

    # 幻觉数
    hallucination_cases = [r for r in results if r["hallucination_suspected"]]
    hallucination_count = len(hallucination_cases)

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
        if not r["route_correct"]
    ]

    # 按类别分组
    categories = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"count": 0, "route_correct": 0, "source_correct": 0, "source_denom": 0, "hallucination": 0}
        categories[cat]["count"] += 1
        if r["route_correct"]:
            categories[cat]["route_correct"] += 1
        if r["source_correct"] is not None:
            categories[cat]["source_denom"] += 1
            if r["source_correct"]:
                categories[cat]["source_correct"] += 1
        if r["hallucination_suspected"]:
            categories[cat]["hallucination"] += 1

    by_category = {}
    for cat, stats in categories.items():
        by_category[cat] = {
            "count": stats["count"],
            "route_accuracy": stats["route_correct"] / stats["count"] if stats["count"] else 0,
            "source_correctness": stats["source_correct"] / stats["source_denom"] if stats["source_denom"] else None,
            "hallucination_count": stats["hallucination"],
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

    return {
        "total_questions": total,
        "summary": {
            "route_accuracy": route_accuracy,
            "answer_relevance": answer_relevance,
            "source_correctness": source_correctness,
            "retrieval_success_rate": retrieval_success_rate,
            "hallucination_count": hallucination_count,
            "relevance_denom": relevance_denom,
            "source_denom": source_denom,
            "retrieval_denom": retrieval_denom,
        },
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

    print("\n" + "=" * 60)
    print(f"=== RAG Agent 评估报告 ===")
    print(f"时间: {now}")
    print(f"数据集: v{dataset_version} ({report['total_questions']} 题)")
    print("=" * 60)

    print("\n【整体指标】")
    print(f"路由准确率:        {s['route_accuracy']*100:.1f}% ({int(s['route_accuracy']*report['total_questions'])}/{report['total_questions']})")
    print(f"答案相关性:        {s['answer_relevance']*100:.1f}% ({int(s['answer_relevance']*s['relevance_denom'])}/{s['relevance_denom']})")
    source_pct = s['source_correctness']*100
    print(f"引用正确率:        {source_pct:.1f}% ({int(s['source_correctness']*s['source_denom'])}/{s['source_denom']})  ← 核心指标")
    print(f"检索成功率:        {s['retrieval_success_rate']*100:.1f}% ({int(s['retrieval_success_rate']*s['retrieval_denom'])}/{s['retrieval_denom']})")
    print(f"疑似幻觉数:        {s['hallucination_count']}")

    print("\n【按类别】")
    for cat, stats in report["by_category"].items():
        route_pct = stats["route_accuracy"] * 100
        line = f"{cat:<18} ({stats['count']:>2}题) 路由 {route_pct:.1f}%"
        if stats["source_correctness"] is not None:
            line += f" | 引用 {stats['source_correctness']*100:.1f}%"
        if stats["hallucination_count"] > 0:
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
            print(f"  {hc['id']} route={hc['route']} 答案无[来源：]  | {hc['question'][:30]}...")

    print("\n" + "=" * 60)


async def main():
    parser = argparse.ArgumentParser(description="RAG Agent 评估脚本")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 题（快速验证）")
    parser.add_argument("--id", type=str, default=None, help="只跑指定题 ID（如 q001）")
    args = parser.parse_args()

    # 加载数据集
    dataset_path = Path(__file__).parent / "dataset.json"
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

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
            for i, q in enumerate(questions, 1):
                print(f"\r[{i}/{len(questions)}] 评估 {q['id']} {q['question'][:30]}...", end="", flush=True)
                result = await eval_one(client, q)
                results.append(result)
                # 实时打印异常
                if result["error"]:
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
