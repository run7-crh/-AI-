"""视觉观察评估夹具生成器（阶段 C）。

诚实边界（与 data/drone 的 synthetic 标注传统一致）：
- 所有夹具都是**程序渲染**的截图/示意图，画面中的文字像素级已知，gold 由渲染
  内容直接导出（gold_status="verified"），不存在编造的"真实损伤"标注。
- 真实损伤照片（鼓包/断桨等）识别率在拿到真实图片前**无法诚实评估**，
  报告显式标注 real_image_coverage=0。
- 示意图的损伤线索来自图内**文字说明**（如"示意图：桨叶末端缺口"），
  检验的是"文字线索 → damage_signals 字段路由"，不是视觉损伤识别。

用法：
    cd backend
    python eval/build_vision_fixtures.py

输出：
    backend/eval/vision_fixtures/*.png
    backend/eval/vision_cases.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURE_DIR = _BACKEND_DIR / "eval" / "vision_fixtures"

FONT_SIZE = 18


def _font(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _cjk_font(size: int = 22):
    """中文字体（示意图说明用）；找不到则返回 None，调用方退回英文说明。"""
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "/System/Library/Fonts/PingFang.ttc"):
        path = Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return None


def _phone_screenshot(lines: list[str], *, accent: str = "red") -> Image.Image:
    """渲染一张手机 App 风格的报错/提示截图（宽 320×高 560）。"""
    img = Image.new("RGB", (320, 560), "#f5f6f7")
    draw = ImageDraw.Draw(img)
    font = _font()
    # 顶部导航栏
    draw.rectangle([0, 0, 320, 56], fill="#1d2b36")
    draw.text((16, 18), "DJI Fly", fill="white", font=font)
    # 弹窗卡片
    draw.rounded_rectangle([28, 160, 292, 400], radius=12, fill="white", outline=accent, width=3)
    y = 190
    for line in lines:
        draw.text((44, y), line, fill="#202124", font=font)
        y += 34
    # 底部状态栏
    draw.rectangle([0, 528, 320, 560], fill="#e8eaed")
    draw.text((16, 536), "settings  safe  me", fill="#5f6368", font=font)
    return img


def _labeled_diagram(caption_zh: str, caption_en: str, shape: str, *, anomaly: bool) -> Image.Image:
    """渲染一张带文字说明的部件示意图（480×360）；说明文字像素级已知。"""
    img = Image.new("RGB", (480, 360), "white")
    draw = ImageDraw.Draw(img)
    font = _font(16)
    cjk = _cjk_font()
    if shape == "propeller":
        draw.ellipse([70, 80, 390, 220], outline="#333333", width=4)   # 桨叶轮廓
        draw.rectangle([225, 130, 257, 170], fill="#333333")           # 桨毂
        if anomaly:
            draw.rectangle([330, 96, 352, 118], fill="white")          # 末端缺口（白块）
            draw.line([330, 96, 352, 118], fill="#333333", width=3)
    elif shape == "battery":
        draw.rounded_rectangle([130, 80, 330, 220], radius=16, outline="#333333", width=4)
        draw.rectangle([330, 130, 352, 170], fill="#333333")           # 极耳
        if anomaly:
            draw.arc([110, 60, 350, 240], start=200, end=340, fill="#333333", width=5)  # 鼓包弧线
    elif shape == "gimbal":
        draw.ellipse([200, 90, 280, 170], outline="#333333", width=4)  # 云台相机
        draw.line([240, 170, 240, 230], fill="#333333", width=5)
        if anomaly:
            for cx, cy in ((210, 110), (262, 150)):
                draw.line([cx - 8, cy, cx + 8, cy], fill="#333333", width=3)  # 磕碰划痕
    caption = caption_zh if cjk else caption_en
    draw.text((36, 290), caption, fill="#202124", font=cjk or font)
    return img


# 每个夹具的渲染参数与 gold（gold 完全由渲染内容导出，不允许自由发挥）。
FIXTURES: list[dict] = [
    {
        "id": "vs01", "category": "app_error_screenshot", "kind": "screenshot",
        "lines": ["ERROR 30010", "Motor overload detected", "Please check propellers"],
        "gold": {"image_type": "screenshot", "text_must_contain": ["ERROR 30010", "Motor overload"],
                 "damage_expected": []},
        "note": "合成渲染 App 报错截图：文字像素级已知",
    },
    {
        "id": "vs02", "category": "app_error_screenshot", "kind": "screenshot",
        "lines": ["ERROR 24", "Compass abnormal", "Recalibrate the compass"],
        "gold": {"image_type": "screenshot", "text_must_contain": ["ERROR 24", "Compass abnormal"],
                 "damage_expected": []},
        "note": "合成渲染 App 报错截图：文字像素级已知",
    },
    {
        "id": "vs03", "category": "app_warning_screenshot", "kind": "screenshot",
        "lines": ["Warning", "Battery temperature too high", "Landing suggested"],
        "gold": {"image_type": "screenshot", "text_must_contain": ["Battery temperature too high"],
                 "damage_expected": []},
        "note": "合成渲染告警截图：无实体损伤，damage 期望为空",
    },
    {
        "id": "vs04", "category": "app_ui_screenshot", "kind": "screenshot",
        "lines": ["Compass Calibration", "Rotate aircraft 360 degrees", "then tap OK"],
        "gold": {"image_type": "screenshot", "text_must_contain": ["Compass Calibration", "360"],
                 "damage_expected": []},
        "note": "合成渲染校准界面截图",
    },
    {
        "id": "vs05", "category": "app_ui_screenshot", "kind": "screenshot",
        "lines": ["Firmware Update", "Version 02.13.0400", "Uploading... 78%"],
        "gold": {"image_type": "screenshot", "text_must_contain": ["02.13.0400", "78%"],
                 "damage_expected": []},
        "note": "合成渲染固件升级界面截图",
    },
    {
        "id": "vs06", "category": "app_warning_screenshot", "kind": "screenshot",
        "lines": ["GPS signal weak", "Return to home advised", "Fly with caution"],
        "gold": {"image_type": "screenshot", "text_must_contain": ["GPS signal weak"],
                 "damage_expected": []},
        "note": "合成渲染 GPS 告警截图",
    },
    {
        "id": "vs07", "category": "labeled_diagram", "kind": "diagram",
        "shape": "propeller", "anomaly": True,
        "caption_zh": "示意图：桨叶末端缺口", "caption_en": "Diagram: propeller tip notch",
        "gold": {"image_type": None, "text_must_contain": ["桨叶末端缺口"],
                 "damage_expected": ["桨叶末端缺口"]},
        "note": "示意图：损伤线索来自图内文字说明（文字→字段路由测试），非视觉损伤识别",
    },
    {
        "id": "vs08", "category": "labeled_diagram", "kind": "diagram",
        "shape": "battery", "anomaly": True,
        "caption_zh": "示意图：电池鼓包", "caption_en": "Diagram: swollen battery",
        "gold": {"image_type": None, "text_must_contain": ["电池鼓包"],
                 "damage_expected": ["鼓包"]},
        "note": "示意图：损伤线索来自图内文字说明",
    },
    {
        "id": "vs09", "category": "labeled_diagram", "kind": "diagram",
        "shape": "gimbal", "anomaly": True,
        "caption_zh": "示意图：云台磕碰痕迹", "caption_en": "Diagram: gimbal scratch",
        "gold": {"image_type": None, "text_must_contain": ["云台磕碰痕迹"],
                 "damage_expected": ["磕碰"]},
        "note": "示意图：损伤线索来自图内文字说明",
    },
    {
        "id": "vs10", "category": "labeled_diagram", "kind": "diagram",
        "shape": "propeller", "anomaly": False,
        "caption_zh": "示意图：电机外观正常", "caption_en": "Diagram: motor looks normal",
        "gold": {"image_type": None, "text_must_contain": ["电机外观正常"],
                 "damage_expected": []},
        "note": "无异常示意图：damage 期望为空（误报检查）",
    },
]


def build() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    cases = []
    for spec in FIXTURES:
        if spec["kind"] == "screenshot":
            image = _phone_screenshot(spec["lines"])
        else:
            image = _labeled_diagram(spec["caption_zh"], spec["caption_en"], spec["shape"], anomaly=spec["anomaly"])
        png_name = f"{spec['id']}.png"
        image.save(FIXTURE_DIR / png_name, format="PNG")
        cases.append({
            "id": spec["id"],
            "category": spec["category"],
            "image": f"eval/vision_fixtures/{png_name}",
            "gold": spec["gold"],
            "gold_status": "verified",
            "note": spec["note"],
        })
    manifest = {
        "version": "vision_v1.0",
        "honesty_note": (
            "全部夹具为程序渲染（合成）图片，gold 由渲染文字像素级导出；"
            "真实损伤照片识别率在真实图片集到位前不可评估（real_image_coverage=0）。"
        ),
        "cases": cases,
    }
    manifest_path = _BACKEND_DIR / "eval" / "vision_cases.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {len(cases)} 个夹具 → {FIXTURE_DIR}")
    print(f"manifest → {manifest_path}")


if __name__ == "__main__":
    build()
