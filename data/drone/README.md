# 无人机售后技术支持知识库（data/drone）

> **重要声明**：本知识库为**技术验证 / 作品集原型**，不代表任何特定无人机企业的内部知识库。
> 本库**没有**任何真实企业的售后工单 / 内部售后数据；
> `cases/` 下的所有案例均为基于公开官方资料构造的**模拟（synthetic）**案例。

## 本数据库服务什么业务

面向"**无人机智能售后技术支持 Agent**"，支持以下业务动作所需的检索知识：

- 无人机产品信息查询（型号 / 规格 / 组成）
- 无人机技术知识查询（GNSS / RTK / 指南针 / IMU / 电池 / 图传 / 感知 / 动力 / 飞行模式）
- 故障现象分析（故障 → 现象 / 原因 / 排查步骤）
- 故障排查（结构化步骤）
- SOP 推荐（起飞前检查 / 电池 / 校准 / 返航 / 排障流程）
- 历史/模拟故障案例检索（`data_type: synthetic`）
- 售后问题结构化（统一 Metadata，配合后续 RAG 导入与质量检查）
- 人工技术支持升级建议（每篇文档的"人工升级条件"）

## 数据来源

- **官方资料（Level A）**：DJI 官方规格页、用户手册、保养手册、官方帮助/支持文章、官方 FAQ、安全指南。
- **监管资料（Level B）**：中国民航局（CAAC）公告、国务院《无人驾驶航空器飞行管理暂行条例》、
  CCAR-92《民用无人驾驶航空器运行安全管理规则》及其解读。
- 全部来源登记于 [`sources/sources.md`](sources/sources.md)（48 个，可追溯）。

## 哪些数据来自官方资料 / 哪些是模拟数据

| 目录 | document_type | data_type | 说明 |
|---|---|---|---|
| `products/` | product | factual | 全部来自官方规格页，逐参数追溯 |
| `technical/` | technical | factual | 技术原理与参数，全部来自官方资料 |
| `troubleshooting/` | troubleshooting | factual | 故障现象/原因/排查步骤全部来自官方支持文章；官方未给出步骤处明确标注 |
| `sop/` | sop | factual | 操作步骤全部来自官方指引，未自行编造维修操作 |
| `safety/` | safety | factual | 来自官方安全指南与监管资料（CAAC） |
| `cases/` | case | **synthetic** | 仅基于公开官方资料构造的模拟场景，**不代表真实售后工单** |

## 目录结构

```
data/drone/
├── sources/sources.md      # 来源登记（source_id / URL / 等级 / 追溯）
├── products/               # 产品知识（4）
├── technical/              # 技术知识（12）
├── troubleshooting/        # 故障排查（13）
├── sop/                    # 标准操作流程（9）
├── safety/                 # 安全知识（6）
├── cases/                  # 模拟售后案例（26）
├── manifest.json           # 文档登记（供 RAG 导入与质量检查）
└── README.md               # 本文件
```

**文档总数：70。**

## Markdown 规范

- 每篇 Markdown 以 **YAML Front Matter** 开头，正文为其后内容。
- 每篇只表达一个知识点，不把多个无关主题塞进同一文件。
- 涉及事实性内容必须有 `source_id`；无法追溯的**不写入**。
- 默认不为满足数量而编造；参数以最新官方资料为准，冲突时以官方最新版本为准。

## Metadata 规范（frontmatter 字段）

| 字段 | 取值 | 说明 |
|---|---|---|
| document_id | `drone_{type}_{theme}` | 稳定标识，不使用随机 UUID |
| document_type | product / technical / troubleshooting / sop / safety / case | |
| product_model | mini_4_pro / matrice_350_rtk / mavic_3_enterprise / agras_t50 / all | `all`=通用（跨机型） |
| component | gnss / rtk / compass / imu / battery / transmission / sensing / gimbal / motors / flight_mode / remote_controller / firmware / product / flight_safety / regulatory 等 | |
| fault_type | 见各故障/案例文档（故障专属） | 仅 troubleshooting / case 使用 |
| source_type | official / regulatory / synthetic | |
| source_id | SOURCE-xxx 列表 | 必须能在 sources.md 找到 |
| source_url | 主来源 URL | |
| version | "1.0" | 文档版本 |
| language | zh-CN | |
| data_type | factual（事实） / synthetic（模拟案例） | |
| created_at / updated_at | YYYY-MM-DD | |
| tags | 主题标签 | 逗号分隔友好 |

## 如何更新知识库

1. 新增/修改文档时保持 Front Matter 五个必填身份字段不变：`document_id`、
   `document_type`、`product_model`、`source_id`、`data_type`。
2. 新增来源必须先在 `sources/sources.md` 登记并分配新 `source_id`。
3. 重新运行 manifest 生成（解析 frontmatter），或按 `manifest.json` 结构手动更新。
4. 事实性内容更新需更新 `updated_at` 与 `version`。

## 如何进行来源追溯

- 每篇文档正文的"来源"节与 frontmatter `source_id` 指向 `sources/sources.md`，
  该表含完整 URL、组织、文档类型、来源等级与访问日期。
- 从任一事实 → `source_id` → `sources.md` → 原始 URL，全程可达。

## 当前知识库的局限性

1. **非真实企业数据**：无任何真实售后工单 / 内部数据，`cases/` 全为 synthetic 模拟。
2. **机型范围有限**：正式产品文档仅覆盖 Mini 4 Pro、Matrice 350 RTK、Agras T50 三个系列
   （Mavic 3 Enterprise 为补充），未覆盖所有 DJI 机型；**不可把 A 机型参数套用到 B 机型**。
3. **部分点未写入**：官方未公开或本次未核验的（轴距、感知相机数量、整机 IP55、人员喷洒安全距离、
   统一亩/时效率、M350 定期保养周期表等）**刻意留白**，避免编造。
4. **故障/SOP 步骤边界**：只写官方资料明确支持的步骤；官方未给出的（如电调异常完整处理流程）
   不补充。
5. **合规时效性**：CAAC 政策有更新（如 2026-05-01 实名登记强制国标），具体适用性以
   UOM（https://uom.caac.gov.cn）与民航局最新办事指南为准。
6. **未接入 RAG**：当前 `manifest.json` 与文档结构面向下一阶段 RAG 接入，尚未配置数据目录/索引。

## 下一阶段 RAG 接入提示（概要）

建议为无人机库使用**独立的 data_dir 与独立 Chroma collection**，避免与现有 AI 知识库冲突；
具体文件级改动在 [`../docs/knowledge_base/drone_build_report.md`](../../docs/knowledge_base/drone_build_report.md) 中说明。