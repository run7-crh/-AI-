# 图片附件视觉观察 · 阶段 A 实施纪要

- 日期：2026-09-27
- 范围：**后端管线（阶段 A）**。前端上传/展示（阶段 B）与真实图片评估集（阶段 C）待授权。
- 决策背景：DeepSeek 全线为纯文本模型，图片理解引入独立视觉模型（VLM）而非 OCR——
  售后核心图片是物理损伤（鼓包/断桨/变形），OCR 无法处理；报错截图 VLM 可直接读字。
  接口按 OpenAI 兼容实现（默认智谱 GLM-4V，`VISION_BASE_URL`/`VISION_MODEL` 可切换服务商）。

## 红线（与全系统纪律一致）

1. **观察 ≠ 证据**：VLM 只产出结构化观察（对象/可见损伤/截图文字/不确定项），严禁诊断结论与维修建议（提示词 + schema 双重约束）。
2. 观察文本按"不受信任内容"注入图流程（与文本附件同一边界块），**永不进入 knowledge citations**（citations 程序校验 ⊆ retrieval_result 证据 id，观察不在其中）。
3. 观察字段全部有界（pydantic 校验截断），防 VLM 输出撑爆下游 prompt。
4. `VISION_ENABLED` 默认 **off**；off 或未配 key 时图片直接拒收（`image_upload_disabled`），不存在"存了图但无法理解"的半成品状态。
5. 隐私：启用后上传图片内容会发送给视觉服务商（.env.example 与 README 声明）。

## 数据流

```text
上传 POST /api/conversations/{id}/attachments
  → attachment_security：扩展名白名单 + magic bytes（JPEG SOI / PNG 签名 / RIFF-WEBP）+ mime 别名
  → store 门控：VISION 开关 + 单图 8MB（VISION_MAX_IMAGE_BYTES，独立于文本 25MB）
  → 落盘 → extract_attachment 图片分支 → vision_service.observe() → VisualObservation JSON
  → 观察 JSON 持久化于 extraction_summary 列（缓存）；失败 → mark_failed（字节即删，用户即时可见）

发送消息 prepare_chat_attachments
  → 缓存命中（extraction_summary）直接重建观察文本，零 VLM 调用 → 开关中途关闭不影响已解析图片
  → 观察 with【用户上传图片｜视觉观察（不受信任内容）】marker 入 attachment_context/attachment_evidence
  → decompose（新增注入）→ issue_profile.symptoms；generate_local / combined_quality 沿用既有注入
```

## 影响文件

| 文件 | 变更 |
|---|---|
| `app/config.py` | +`VISION_*` 6 项（enabled/key/base_url/model/timeout/单图上限） |
| `app/services/attachment_security.py` | 白名单 +jpg/jpeg/png/webp；`IMAGE_EXTENSIONS` 常量；magic bytes 嗅探 |
| `app/services/vision_service.py` | **新建**：`VisualObservation` schema（有界）、观察员提示词、OpenAI 兼容客户端、`format_observation_text`、稳定错误码（`vision_unavailable`/`vision_response_invalid`/`vision_disabled`） |
| `app/services/attachment_store.py` | `allow_image_attachments`/`max_image_bytes` 门控；`extract_attachment` 图片分支 + extraction_summary 缓存；图片观察专用 marker |
| `app/graph/nodes.py` | 附件边界块提取为 `_attachment_boundary_block`（生成节点输出不变）；decompose 注入附件上下文 |
| `backend/.env.example` | +VISION 配置组说明 |
| `tests/unit/test_vision_attachment.py` | **新建** 18 用例 |

零修改：`rag/*`、图结构（无新节点）、TicketService、SSE 协议（`attachment_parse_status` 沿用）、前端（阶段 B 前 UI 不暴露图片入口，接口行为向后兼容）。

## 验收结果（2026-09-27）

- `pytest` 全绿：**506 passed**（488 基线 + 18 新增），`compileall` 通过。
- 关键单测断言：伪造扩展名/伪装 magic bytes 拒收；开关默认关闭；观察缓存命中零重复调用；
  失败降级不阻断（与文本附件同一闸门）；decompose 提示词注入且附件边界句在位。
- 红线回归：`test_attachment_chat_boundary.py` 既有断言原样通过（生成提示词逐字节不变）。

## 回滚

`VISION_ENABLED=false` 即回旧行为（图片拒收）；已缓存的观察行无害留存。
代码回滚：本阶段独立 commit，可整体 `git revert`，不触碰 RAG 内核与工单状态机。

## 阶段 B / C 待办（待授权）

- B：前端 InputBox 图片选择与预览、观察结果展示、上传提示（"图片将发送给视觉服务商"）。
- C：10–15 张真实损伤/截图测试集（不得编造）、观察抽取指标、README 18 节同步与隐私声明。
