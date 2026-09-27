"""VLM 结构化观察抽取（阶段 A：图片附件 → 视觉观察）。

角色边界（不可妥协）：
- 视觉模型是"观察员"，不是"诊断员"：只描述图片客观可见内容（对象/现象/截图文字），
  严禁产出诊断结论、维修建议、安全判断。
- 观察文本与文本附件一样按"不受信任用户资料"进入图流程（decompose/生成/质量检查），
  永不进入 knowledge citations（citations 只能引用 retrieval_result 的证据 id）。

接口为 OpenAI 兼容 chat.completions（默认智谱 GLM-4V），经 langchain_openai 复用
项目既有依赖；更换服务商只需改 VISION_BASE_URL / VISION_MODEL 配置。
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

# 观察字段的硬上限：VLM 输出不可信，先在 schema 层截断/拒绝，防止撑爆下游 prompt。
_MAX_VISIBLE_TEXT_CHARS = 2000
_MAX_LIST_ITEMS = 10
_MAX_ITEM_CHARS = 200
_MAX_NOTE_CHARS = 500


class VisualObservation(BaseModel):
    """单张图片的结构化观察结果（全部字段有界）。"""

    image_type: Literal["screenshot", "physical", "unclear"] = "unclear"
    visible_text: str = ""              # 截图内可见文字的逐字转录；非截图为空
    objects: list[str] = Field(default_factory=list)      # 可见部件/对象
    damage_signals: list[str] = Field(default_factory=list)  # 可见损伤/异常信号
    notes: str = ""                     # 图片质量说明（模糊/过暗/遮挡）
    uncertain: str = ""                 # 无法确认的内容

    @field_validator("visible_text")
    @classmethod
    def _bound_visible_text(cls, value: str) -> str:
        return value[:_MAX_VISIBLE_TEXT_CHARS]

    @field_validator("notes", "uncertain")
    @classmethod
    def _bound_notes(cls, value: str) -> str:
        return value[:_MAX_NOTE_CHARS]

    @field_validator("objects", "damage_signals")
    @classmethod
    def _bound_lists(cls, value: list[str]) -> list[str]:
        return [item[:_MAX_ITEM_CHARS] for item in value[:_MAX_LIST_ITEMS]]


class VisionServiceError(Exception):
    """带稳定错误码的视觉观察失败（不携带上游报文细节）。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# 观察员提示词：JSON-only 输出 + 显式禁止诊断/建议 + 看不清就承认看不清。
OBSERVATION_PROMPT = """你是无人机售后系统的图片观察员。只描述图片中客观可见的内容。

绝对禁止：诊断故障原因、给出维修建议、判断是否安全、推测事件经过。
只输出一个 JSON 对象（不要输出任何其他文字），字段：
{"image_type": "screenshot|physical|unclear",
 "visible_text": "截图内可见文字的逐字转录（限2000字内；不是截图则为空字符串）",
 "objects": ["观察到的部件或对象，如：桨叶、电机、电池、云台、遥控器、手机App界面"],
 "damage_signals": ["可见的损伤或异常，如：桨叶缺口、电池鼓包、外壳裂纹、进水痕迹；没有则为空数组"],
 "notes": "图片质量说明（模糊/过暗/遮挡/非无人机相关），没有则为空字符串",
 "uncertain": "无法确认的内容，没有则为空字符串"}

规则：看不清就写看不清并放进 uncertain；不得编造看不清的细节；空数组用 [] 而不是 null。"""


def format_observation_text(observation: VisualObservation) -> str:
    """把观察结果格式化为注入 prompt 的有界文本（与结构化字段同源）。"""
    type_labels = {"screenshot": "屏幕截图", "physical": "实物照片", "unclear": "类型不明"}
    lines = [f"[图片类型] {type_labels[observation.image_type]}"]
    if observation.visible_text:
        lines.append(f"[截图可见文字] {observation.visible_text}")
    if observation.objects:
        lines.append(f"[可见对象] {'、'.join(observation.objects)}")
    if observation.damage_signals:
        lines.append(f"[可见异常] {'；'.join(observation.damage_signals)}")
    if observation.uncertain:
        lines.append(f"[无法确认] {observation.uncertain}")
    if observation.notes:
        lines.append(f"[图片质量] {observation.notes}")
    if len(lines) == 1 and observation.image_type == "unclear":
        lines.append("[观察] 未提取到有效信息")
    return "\n".join(lines)


def _extract_json_payload(raw: str) -> dict:
    """从模型回复中稳健提取 JSON 对象（容忍代码围栏与前后杂讯）。"""
    text = raw.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no_json_object")
    return json.loads(text[start : end + 1])


class VisionObservationService:
    """OpenAI 兼容视觉端点客户端；只在配置完整时可用。"""

    @classmethod
    def from_settings(cls) -> "VisionObservationService | None":
        from app.config import settings

        if not settings.VISION_ENABLED or not settings.VISION_API_KEY.strip():
            return None
        return cls(
            api_key=settings.VISION_API_KEY.strip(),
            base_url=settings.VISION_BASE_URL,
            model=settings.VISION_MODEL,
            timeout_seconds=settings.VISION_TIMEOUT_SECONDS,
        )

    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float):
        if not api_key or not api_key.strip():
            # 无 key 的实例不允许构造，避免"半配置"状态静默发出无鉴权请求。
            raise VisionServiceError("vision_not_configured")
        self.model = model
        self.timeout_seconds = timeout_seconds
        # 延迟导入：未启用视觉的部署不必加载 langchain。
        from langchain_openai import ChatOpenAI

        self._llm = ChatOpenAI(
            model=model,
            api_key=api_key.strip(),
            base_url=base_url,
            temperature=0,          # 观察要求稳定，不做发散
            max_retries=1,          # 上传是同步交互，失败快速反馈优于长重试
            timeout=timeout_seconds,
        )

    async def observe(self, payload: bytes, detected_mime: str) -> VisualObservation:
        """对单张图片产出结构化观察；失败抛 VisionServiceError（稳定错误码）。"""
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise VisionServiceError("vision_payload_invalid")
        encoded = base64.b64encode(bytes(payload)).decode("ascii")
        message = {
            "role": "user",
            "content": [
                {"type": "text", "text": OBSERVATION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{detected_mime};base64,{encoded}"}},
            ],
        }
        try:
            response = await self._llm.ainvoke([message])
        except Exception:
            # 网络/鉴权/超时等上游错误一律收敛为稳定错误码，不泄露报文。
            logger.warning("vision observe 调用失败")
            raise VisionServiceError("vision_unavailable") from None
        raw = response.content if isinstance(response.content, str) else "".join(
            part.get("text", "") for part in response.content if isinstance(part, dict)
        )
        try:
            return VisualObservation.model_validate(_extract_json_payload(raw))
        except (ValueError, json.JSONDecodeError, ValidationError):
            logger.warning("vision observe 返回无法解析为观察 JSON")
            raise VisionServiceError("vision_response_invalid") from None
