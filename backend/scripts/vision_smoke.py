"""视觉观察冒烟测试：生成一张"报错截图"风格测试图 → 真实调用 VLM → 打印观察结果。

用法（backend 目录下）：
    python scripts/vision_smoke.py

前置：backend/.env 中 VISION_ENABLED=true 且 VISION_API_KEY 已配置。
只打印观察结果，绝不打印 API Key。
"""

import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ 入 sys.path

from app.config import settings
from app.services.attachment_security import validate_attachment_bytes
from app.services.vision_service import VisionObservationService, format_observation_text


def build_test_image() -> bytes:
    """生成一张含报错文字的 PNG（默认字体不含中文，用英文报错文案）。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (360, 180), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([6, 6, 353, 173], outline="red", width=3)
    draw.text((16, 24), "DJI FLY  ERROR 30010", fill="black")
    draw.text((16, 64), "Motor overload detected", fill="black")
    draw.text((16, 104), "Please check propellers", fill="black")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


async def main() -> int:
    print(f"VISION_ENABLED  = {settings.VISION_ENABLED}")
    print(f"VISION_MODEL    = {settings.VISION_MODEL}")
    print(f"API_KEY 已配置   = {bool(settings.VISION_API_KEY.strip())}")
    service = VisionObservationService.from_settings()
    if service is None:
        print("✗ 视觉服务未启用：请检查 VISION_ENABLED 与 VISION_API_KEY")
        return 1
    payload = build_test_image()
    item = validate_attachment_bytes("vision_smoke.png", payload, "image/png")  # 走真实安全校验
    print(f"安全校验通过     = detected_mime={item.detected_mime}, {item.size_bytes} bytes")
    print("正在调用视觉模型……")
    observation = await service.observe(payload, item.detected_mime)
    print("\n---- 观察结果（注入图流程的文本形态）----")
    print(format_observation_text(observation))
    print("\n---- 结构化 JSON ----")
    print(observation.model_dump_json(indent=2, ensure_ascii=False))
    print("\n✓ 冒烟通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
