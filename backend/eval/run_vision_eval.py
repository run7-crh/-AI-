"""视觉观察评估脚本（阶段 C）。

用法：
    cd backend
    python eval/run_vision_eval.py            # 全量（10 夹具）
    python eval/run_vision_eval.py --limit 3  # 只跑前 3 个

前置：backend/.env 中 VISION_ENABLED=true 且 VISION_API_KEY 已配置。

输出：
    1. 控制台汇总
    2. backend/eval/reports/vision_report_YYYYMMDD_HHMMSS.json

诚实口径：
- 数据集全部为程序渲染夹具（gold_status=verified，像素级已知文字）；
- 真实损伤照片覆盖为 0，本报告只验证"观察抽取 / 截图转录 / 文字线索路由"能力，
  不代表真实损伤识别率。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_TZ = timezone(timedelta(hours=8))


# ---------- 评分辅助（纯函数，单测覆盖） ----------

def _case_text_recall(observation: dict, gold_substrings: list[str]) -> tuple[float, int]:
    """截图转录召回：gold 子串在 visible_text 中命中比例（大小写不敏感）。

    返回 (recall, 分母)；分母为 0 时 recall 记 1.0（无断言即无失败），
    调用方按"有 gold 的夹具数"汇总，避免把空分母当成满分。
    """
    visible = str(observation.get("visible_text", "") or "").casefold()
    if not gold_substrings:
        return 1.0, 0
    hits = sum(1 for needle in gold_substrings if str(needle).casefold() in visible)
    return hits / len(gold_substrings), len(gold_substrings)


def _case_damage_signals(observation: dict) -> list[str]:
    value = observation.get("damage_signals")
    return [str(item) for item in value] if isinstance(value, list) else []


def _case_damage_false_positive(observation: dict) -> bool:
    """无损伤 gold 的夹具是否出现幻觉损伤信号。"""
    return len(_case_damage_signals(observation)) > 0


def _case_damage_cue_hit(observation: dict, gold_keywords: list[str]) -> tuple[bool, int]:
    """文字线索 → damage_signals 路由：关键词按字符级容忍匹配（≥0.75 覆盖）。

    中文无词边界且模型可能插入"有/了"等助词（"桨叶末端缺口"→"桨叶末端有缺口"），
    纯子串匹配会把语义正确的改写误判为未命中；字符覆盖率是可解释的容忍口径。
    """
    joined = "；".join(_case_damage_signals(observation)).casefold()
    if not gold_keywords or not joined:
        return False, len(gold_keywords)
    coverage_sum = 0.0
    for keyword in gold_keywords:
        needle = str(keyword).casefold()
        if needle in joined:
            coverage_sum += 1.0
            continue
        chars = [ch for ch in needle if ch.strip()]
        if not chars:
            continue
        covered = sum(1 for ch in chars if ch in joined) / len(chars)
        coverage_sum += covered
    average = coverage_sum / len(gold_keywords)
    return average >= 0.75, len(gold_keywords)


def _case_image_type_correct(observation: dict, gold_image_type: str | None) -> bool | None:
    """image_type 判定；gold 为 None（示意图类）时不适用，返回 None。"""
    if not gold_image_type:
        return None
    return observation.get("image_type") == gold_image_type


# ---------- 评估主流程 ----------

def _load_cases(limit: int | None) -> list[dict]:
    manifest_path = _BACKEND_DIR / "eval" / "vision_cases.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    return cases[:limit] if limit else cases


async def eval_case(service, case: dict) -> dict:
    from app.services.vision_service import VisionServiceError

    png_path = _BACKEND_DIR / case["image"]
    payload = png_path.read_bytes()
    started = time.monotonic()
    try:
        observation_model = await service.observe(payload, "image/png")
        observation = observation_model.model_dump()
        error = None
    except VisionServiceError as exc:
        observation = {}
        error = exc.code
    except Exception:
        observation = {}
        error = "vision_unexpected_error"
    elapsed = round(time.monotonic() - started, 2)
    gold = case["gold"]

    recall, recall_denominator = _case_text_recall(observation, gold.get("text_must_contain", []))
    damage_expected = gold.get("damage_expected", [])
    if error:
        image_type_ok = None if gold.get("image_type") is None else False
        damage_fp = False
        cue_hit, cue_denominator = False, len(damage_expected)
    else:
        image_type_ok = _case_image_type_correct(observation, gold.get("image_type"))
        damage_fp = _case_damage_false_positive(observation) and not damage_expected
        cue_hit, cue_denominator = _case_damage_cue_hit(observation, damage_expected)

    return {
        "id": case["id"],
        "category": case["category"],
        "gold_status": case.get("gold_status"),
        "error": error,
        "elapsed_seconds": elapsed,
        "observation": observation if not error else None,
        "image_type_ok": image_type_ok,
        "text_recall": recall,
        "text_recall_hits": round(recall * recall_denominator),
        "text_recall_denominator": recall_denominator,
        "damage_false_positive": damage_fp,
        "damage_cue_hit": cue_hit if damage_expected else None,
        "damage_cue_denominator": cue_denominator,
    }


def aggregate(cases: list[dict], results: list[dict], *, model: str, base_url: str) -> dict:
    scored = [item for item in results if item["error"] is None]
    schema_validity = len(scored) / len(results) if results else None

    type_items = [(c, r) for c, r in zip(cases, results) if c["gold"]["image_type"]]
    type_correct = sum(1 for _, r in type_items if r["image_type_ok"])

    recall_hits = sum(r["text_recall_hits"] for r in results)
    recall_total = sum(r["text_recall_denominator"] for r in results)

    no_damage = [r for c, r in zip(cases, results) if not c["gold"]["damage_expected"]]
    fp_count = sum(1 for r in no_damage if r["damage_false_positive"])

    cue_cases = [r for r in results if r["damage_cue_denominator"] > 0]
    cue_hits = sum(1 for r in cue_cases if r["damage_cue_hit"])

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    return {
        "generated_at": datetime.now(_TZ).isoformat(),
        "model": model,
        "provider_host": urlparse(base_url).hostname or base_url,
        "total_cases": len(cases),
        "dataset_kind": "synthetic_rendered_only",
        "real_image_coverage": 0,
        "metrics": {
            # schema 有效性：观察调用成功且可解析的比例
            "schema_validity": ratio(len(scored), len(results)),
            # 截图 image_type 判定（仅 gold 含 image_type 的夹具）
            "image_type_accuracy": ratio(type_correct, len(type_items)),
            # 截图文字转录召回（按 gold 子串总数计分母）
            "text_recall": ratio(recall_hits, recall_total),
            # 幻觉损伤信号：无损伤 gold 夹具中出现 damage_signals 的比例（期望 0）
            "damage_false_positive_rate": ratio(fp_count, len(no_damage)),
            # 文字线索 → damage_signals 路由命中率（仅示意图类）
            "damage_cue_hit_rate": ratio(cue_hits, len(cue_cases)),
        },
        "denominators": {
            "image_type_cases": len(type_items),
            "text_recall_substrings": recall_total,
            "no_damage_cases": len(no_damage),
            "damage_cue_cases": len(cue_cases),
        },
        "honesty_note": (
            "数据集全部为程序渲染的合成截图/示意图（gold 由渲染文字像素级导出）；"
            "无真实损伤照片，本报告不构成真实损伤识别率的任何结论。"
        ),
        "per_case": results,
    }


async def main_async(limit: int | None) -> int:
    from app.config import settings
    from app.services.vision_service import VisionObservationService

    service = VisionObservationService.from_settings()
    if service is None:
        print("✗ 视觉服务未启用：请检查 VISION_ENABLED 与 VISION_API_KEY")
        return 1
    cases = _load_cases(limit)
    print(f"视觉观察评估：{len(cases)} 个夹具，model={settings.VISION_MODEL}")
    results = []
    for case in cases:
        result = await eval_case(service, case)
        status = result["error"] or "ok"
        print(f"  {case['id']} [{status}] {result['elapsed_seconds']}s "
              f"recall={result['text_recall']:.2f} ({result['text_recall_hits']}/{result['text_recall_denominator']})")
        results.append(result)

    report = aggregate(cases, results, model=settings.VISION_MODEL, base_url=settings.VISION_BASE_URL)
    report_dir = _BACKEND_DIR / "eval" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(_TZ).strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"vision_report_{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n==== 视觉观察评估汇总 ====")
    metrics = report["metrics"]
    for name, value in metrics.items():
        display = f"{value * 100:.1f}%" if value is not None else "N/A（分母为 0）"
        print(f"{name:32s} {display}")
    print(f"报告 → {report_path}")
    print(f"诚实口径：{report['honesty_note']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="视觉观察评估")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 个夹具")
    args = parser.parse_args()
    return asyncio.run(main_async(args.limit))


if __name__ == "__main__":
    sys.exit(main())
