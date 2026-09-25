---
title: 无人机售后技术支持知识库构建报告
document_type: build_report
version: "1.0"
language: zh-CN
created_at: 2026-09-18
updated_at: 2026-09-18
---

# 无人机售后技术支持知识库构建报告

> 免责声明：本知识库为**技术验证 / 作品集原型**，不代表任何特定无人机企业的内部知识库。
> 不含任何真实企业内部售后数据；`synthetic` 案例均为基于公开官方资料构造的模拟场景。

---

## 1. 构建目标

为将现有的 AI / 编程学习问答系统进一步垂直化，建设一个面向**「无人机智能售后技术支持 Agent」**的
高质量、可追溯、适合 RAG 检索的垂直领域知识库。目标业务能力：

- 无人机产品信息查询
- 无人机技术知识查询
- 故障现象分析
- 故障排查
- SOP 推荐
- 历史 / 模拟故障案例检索
- 售后问题结构化
- 人工技术支持升级建议

构建原则为「**质量优先于数量**」：所有事实性内容必须可追溯，无法验证的信息宁可不写。

## 2. 数据来源

共登记 **48** 个来源（详见 `data/drone/sources/sources.md`），全部进入知识库。覆盖三类产品系列：

| 产品系列 | 主要型号 | 来源 |
|---|---|---|
| 消费级 | DJI Mini 4 Pro | SOURCE-001 ~ SOURCE-019 |
| 行业级 | 大疆 Matrice 350 RTK（备用：Mavic 3 Enterprise / Matrice 30） | SOURCE-020 ~ SOURCE-033 |
| 农业级 | DJI Agras T50 | SOURCE-034 ~ SOURCE-039 |
| 民航监管 | CAAC / 交通运输部 法规与平台 | SOURCE-040 ~ SOURCE-048 |

来源类型包括：官方产品规格页、用户手册（PDF）、帮助中心 Support Article、官方 FAQ、
官方技术支持页、官方安全指南/安全概要、民航监管法规与国家平台。

## 3. 来源可信度

| 等级 | 含义 | 数量 | 占比 |
|---|---|---|---|
| **Level A** | 无人机厂商官方网站 / 官方手册 / 官方支持 / 官方 FAQ / 官方安全文档 | 35 | 72.9% |
| **Level B** | 政府与民航监管机构（CAAC、交通运输部、中国政府网）、行业监管平台 | 13 | 27.1% |
| **Level C** | 高质量技术网站（本批次未采用） | 0 | 0% |

- 事实性内容尽量以 **DJI 官方资料（Level A）** 为唯一来源；法规与监管内容采用 **CAAC（Level B）**。
- 刻意**避开**了百度知道、营销软文、SEO 文章、自媒体、内容农场、AI 二手资料等不可核验来源。
- 官方整本 PDF（SOURCE-024/025/026/033）仅登记 URL 与元数据，**未把 PDF 全文复制进 Git**，
  规避版权与仓库体积风险；正文仅提取并结构化其中的事实要点。

## 4. 知识库目录

```
data/drone/
├── sources/          # 来源登记表 sources.md（48 个来源）
├── products/         # 产品知识（4 篇）
├── technical/        # 技术知识（12 篇）
├── troubleshooting/  # 故障排查（13 篇）
├── sop/              # 标准操作流程（9 篇）
├── safety/           # 安全知识（6 篇）
├── cases/            # 模拟售后案例（26 篇，全部 synthetic）
├── manifest.json     # 全部 70 篇文档的 RAG 导入清单
└── README.md         # 知识库说明 / 规范 / 更新与追溯方法
```

采用独立 `data/drone/` 目录，**未触碰** `data/raw/` 与 `data/processed/` 任何现有资产。

## 5. 文档数量

- **知识文档总数：70 篇**
- `manifest.json` 登记文档：70 篇（与逐文件扫描一致）
- 另有 2 篇非知识文档：`sources/sources.md`、`README.md`

## 6. 产品数量

- **正式产品文档：4 篇**（Mini 4 Pro、Matrice 350 RTK、Mavic 3 Enterprise、Agras T50）
- 备用型号补充：Mavic 3 Enterprise / Matrice 30（在 SOURCE 中登记，不与非行业型号混用）
- 覆盖：消费级、行业级、农业级三个细分市场，且**参数严格按型号分开记录**，不跨型号套用。

## 7. 故障类型数量

- 独立故障排查文档：**13 篇**（GPS 异常、罗盘异常、IMU 异常、图传黑屏、遥控器信号弱、
  遥控器失联/未连接、无法起飞、RTK 信号弱、视觉标定、固件升级失败、电池不充电、
  电池鼓包、飞行器已断开）
- 模拟案例覆盖的故障场景：**26 个**（含上述故障的变体与组合场景，如低电量迫降、低温电池、
  失控返航、RTK 中断、农业防腐蚀等）
- 合计可检索故障/场景：**约 36 类**（13 独立文档 + 26 案例场景中与 13 篇重叠部分的增量）。

## 8. SOP 数量

- **标准操作流程：9 篇**（起飞前检查、电池检查与养护、指南针校准、IMU 校准、GPS 异常排查、
  对频、图传异常排查、返航设置、农业电池安全养护）。

## 9. 模拟案例数量

- **synthetic 模拟案例：26 篇**（`data/drone/cases/`，全部标记 `data_type: synthetic`）。
- 每个案例均声明 `case_type: synthetic`，**未声称**为真实客户工单或真实企业售后数据；
  用途仅为测试 Agent「问题 → 识别故障 → 检索知识 → 命中 SOP → 有依据排查」的能力链路。

## 10. 官方资料数量

- **Level A（DJI 官方）来源：35 个**
- 由官方资料支撑的 `factual` 文档：**44 篇**（产品 4 + 技术 12 + 故障 13 + SOP 9 + 安全 6）

## 11. 非官方资料数量

- **Level B（CAAC / 监管）来源：13 个** —— 用于安全合规与飞行管理章节
- **Level C（第三方技术网站）：0 个**
- 官方 PDF 的转述页 SOURCE-027 归入 Level B 并明确标注「转录」，仅用于交叉印证保养要点。

## 12. 数据质量检查结果

采用 Python 自动脚本对 70 篇文档执行结构校验与字段级 QC：

| 检查项 | 结果 |
|---|---|
| 空文档 / 极小文档（<50 字符） | 0 |
| 缺失 frontmatter | 0 |
| 关键元数据字段缺失（document_id/type/model/source_id/data_type 等） | 0 |
| 重复 `document_id` | 0 |
| 重复文档名 | 0 |
| `document_type` 非法或与 ID 前缀不一致 | 0 |
| `data_type` 非法 | 0 |
| factual 文档无来源引用 | 0 |
| 引用未知/未登记 `source_id` | 0 |
| 案例未标记 synthetic | 0 |
| 故障/案例缺 `fault_type` | 0 |
| 故障排查缺「适用范围」 | 0 |
| Markdown 代码围栏不平衡 | 0 |
| 知识文档总数与 manifest 一致 | 70 = 70 ✓ |

**QC 结论：0 个问题**。`factual` 内容均有唯一可追溯来源；`synthetic` 案例在正文中显式声明「模拟场景，非真实售后数据」。

## 13. 未解决的信息冲突

- **跨厂商 / 跨型号参数冲突：已按型号隔离**，未将任一产品的参数写入其他产品文档，不存在知识混淆。
- **备用型号差异**（Mavic 3E / Matrice 30 与 M350 的参数不同）已在来源登记与产品文档中注明「备用型号，
  参数勿与非行业型号混用」。
- **法规时效约定**：民航实名登记强制国标（SOURCE-042，2026-05-01 实施）与《暂行条例》(SOURCE-041/047)、
  CCAR-92（SOURCE-046）在版本与生效时间上存在差异，已在安全合规文档中按「现行有效」口径引用并注明生效日期，
  作为待后续核验项记录，未强行抹平。

## 14. 当前知识库局限性

1. **无真实企业内部售后数据**：所有案例均为 synthetic，不构成真实故障分布或工单画像；
   故障频次、返修率、零件寿命率等运营级指标全部缺失。
2. **产品覆盖有限**：仅 Mini 4 Pro / Matrice 350 RTK / Mavic 3 Enterprise / Agras T50 4 个主型号，
   远非厂商全产品线。
3. **重 DJI 单厂商**：Level A 全部来自大疆官方；其他厂商（自研、其他品牌）技术资料未纳入，存在厂商倾向。
4. **维修级操作缺失**：官方公开资料不含拆机维修、内部电路、备件更换的授权操作，故本库不含深度维修知识。
5. **部分来源为官方 PDF 转述**：SOURCE-027 为保养手册转录页（Level B），精确度低于原始 PDF。
6. **法规持续演进**：民航实名登记与运行识别规范处于政策窗口期，具体条款可能随新规调整。
7. **来源 URL 未经逐条在线可达性复测**：访问日期统一记 2026-09-18，个别长链后续可能失效（已登记原始 URL 供追踪）。

## 15. 后续 RAG 接入建议

当前知识库**已具备进入下一阶段 RAG 接入的条件**（结构、元数据、来源追溯、manifest 均已就绪）。建议下阶段修改的代码文件（本阶段均未改动）：

1. `backend/app/config.py` — `KB_DATA_DIR` 当前指向 `data/raw`；建议新增/切换配置指向 `data/drone`，
   或将 drone 作为第二个可选的 knowledge-base 目录（避免覆盖现有 AI 知识库）。
2. `backend/rag/readers.py` — 增加对 `data/drone` 各子目录（products/technical/troubleshooting/sop/safety/cases）
   的遍历读取，并解析 YAML frontmatter 中的 `document_id / document_type / product_model / component /
   fault_type / data_type / source_id` 作为向量元数据（metadata）。
3. `backend/rag/indexer.py` / index 构建逻辑 — 将 manifest.json 作为导入清单，按 `data_type`（factual / synthetic）
   区分数据源；若需隔离，可为 drone 建立独立 Chroma collection（如 `drone_kb`，`CHROMA_COLLECTION_NAME` 可配置已支持）。
4. LangGraph RAG 检索/重排节点 — 依据 `document_type` 支持按类型过滤（如故障→优先检索 troubleshooting/sop/cases），
   并可在回答中回填 `source_id` 与来源 URL 实现可追溯引用。
5. （可选）新增售后问题结构化与「人工升级建议」相关 prompt / 评测用例。

> 接入时建议**先在小范围 collection 验证**检索质量，再决定是否与现有 AI 知识库合并或独立部署。

---

### 未进入知识库的资料来源与原因

- 未采用任何百度知道、营销软文、SEO 文章、自媒体、内容农场、二手转载、无法核验出处的网站。
- 官方整本 PDF 未全文复制进 Git（版权 / 体积），仅保留 URL、名称、机构、访问时间等元数据。
- 凡无法验证的具体参数或维修步骤，均未写入，宁缺毋滥。

### 合规与 Git 说明

- 本次未删除、移动、覆盖任何 `data/raw/`、`data/processed/` 或 `README.md` 等现有文件。
- 未修改 `backend/`、`frontend/` 任何业务代码（LangGraph / RAG / Reader / Indexer / Chroma / FastAPI / 前端）。
- 未修改 `.gitignore` 任何既有忽略规则；不包含 API Key、Token、密码、`.env`、私人或企业内部数据。
- 无人机知识库的 Markdown 文档与 manifest 可纳入 Git；原始 PDF 仅以元数据形式登记。