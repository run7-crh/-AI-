# 无人机售后知识库 —— 修复报告

- **日期**：2026-09-18
- **范围**：`data/drone/` 全库（71 篇 Markdown + `manifest.json` + `sources/sources.md`）
- **修复原则**：只补元数据与机型护栏、修正可验证的事实错误；**不篡改既有硬件/技术事实**。
- **方法说明**：审计先经确定性脚本全量比对（frontmatter/manifest/正文内联引用/来源注册），再对子代理判定逐处用原始页面/文件**人工复核**；凡标【已核验】处均为取到原始证据的结论。多处子代理"来源不支撑"误报被推翻（见 §4）。

---

## 1. 已修复问题

### P1-1｜frontmatter `data_type` 全库缺失（70/70）
磁盘前文原本无 `data_type`（manifest 有）。已按 manifest 为全部文档补齐。修复后分布：synthetic 26、factual 45（合计 71）。

### P1-2｜manifest 与正文 `source_id` 不一致（26 篇）
前端 `source_id` 与正文内联引用完全一致（这是事实使用集合），manifest 为陈旧侧。已将 manifest 的 `source_id` 对账到各文档实际引用。

### P1-3｜RTH 跨机型混淆（拆分）
- `sop/drone_sop_rth_config.md`：`product_model` `all → mini_4_pro`；移除内嵌的 M350"Pilot 2 / 10 秒未操作自动返航"步骤与 SOURCE-025；加消费级机型作用域声明，指向新文档。
- 新增 `sop/drone_sop_rth_config_m350.md`（`matrice_350_rtk`，SOURCE-025）：仅含 M350 返航设置/Smart RTH/低电量 RTH/Failsafe RTH（信号丢失约 6 秒自动启用，取自 M350 产品规格）/急停取消；不转写未经核验的"10 秒未操作"说法。
- `manifest.json` 同步（71 条，新增 1 条）。

### P0-A｜CAAC 机型分类错误（Mini 4 Pro 误判为"微型"）
`drone_safety_caac_compliance.md`【已核验】：依《无人驾驶航空器飞行管理暂行条例》（国令第761号）第62条
- 修正表格"微型"行：删除误植的"最大起飞重量 ≤7 kg"（该上限属于**轻型**；微型无此条款）；
- 修正结论行：Mini 4 Pro 因最大平飞速度约 57.6 km/h>40 km/h、可飞真高超 50 m，**不满足微型 → 应为轻型**；
- 补充分类依据与说明。

### P1-4｜RTK 跨机型技术文护栏
`drone_technical_rtk_differential.md` 元数据 `matrice_350_rtk` 但含 Agras T50 整节。检索层实测**无 `product_model` 硬过滤**（纯语义召回+rerank），故非"取不到"，但存在溯源机型错标风险。已加"跨机型，按机型取段"护栏，并在底部来源行补上正文已引的 SOURCE-039。

### P1-5｜`product_model=all` 文档机型护栏
`drone_sop_gps_troubleshoot.md`、`drone_troubleshooting_gps_abnormal.md` 加"依据消费级机型验证、行业/农业机型以各机型手册为准"声明。其余 `all` 类文档结合 P1-3/1-4 一并缓解。

### P1-7/8｜`sources.md` 登记表自相矛盾【已核验】
- 原表自称"全部 48 个均进入知识库"为**假**：SOURCE-020/026/031/033 无人引用。已改为如实描述（44 引用 + 4 备用存放）。
- Level 计数修正：按图例实测 A=39（001..039）、B=9（040..048）；原文 35/13 有误。
- SOURCE-027 等级 `B → A` 并标注"官方手册第三方镜像，建议优先引用官方 SOURCE-026"。

### P2｜一致性与笔误修复
- `drone_technical_controllers.md`：删除污染词"固件 **.NET** 版本"→"固件版本"。
- `drone_technical_smart_battery.md`：底部来源列表去重、排序。
- `drone_sop_preflight_check.md` L31：限飞区查询引用 `SOURCE-003 → SOURCE-019`（正确来源）。
- `cases/s007`、`cases/s011`：正文"来源"行补上与 frontmatter 一致的引用。

---

## 2. 保留待人工核验（未改动，因不满足"可验证"边界）
- **P1-6** `drone_technical_firmware.md` L19：消费级 Mini"或通过 DJI Assistant 2（电脑端）升级"。DJI Fly 机型常规仅经 App 升级，疑点存在但置信度低（0.6），**未擅改**，需以官方支持页确认。
- **P2-6** 法规具体条文在线未逐字比对（仍标注）："飞行前 1 日 12 时前申请""设施上空 120m 以下起飞前 1 小时确认""未实名罚款 200 元/情节严重 2 千–2 万""国标 2026-05-01 实施 + 12 个月过渡期"。避免再依赖记忆改写，留表待官方原文逐字。
- RTK 文档"中国区网络 RTK 前两年免费、第三年起收费"（SOURCE-022）：断言具体，需官方 FAQ 原文确认。

---

## 3. 验证结果（修复后复跑全量确定性校验）
- 71 篇文档：无重复 `document_id`；
- frontmatter `source_id` == 正文内联 SOURCE 引用（完全匹配，无 in-fm-not-body / in-body-not-fm）；
- frontmatter 与 manifest：模型/类型/source_id/data_type 全部一致；
- 全部被引 SOURCE 均在 `sources.md` 有登记，无断裂引用；
- `data_type` 分布：synthetic 26 / factual 45。

---

## 4. 审计方法学的关键教训（重要）
多个子代理/初审把"来源真地支撑正文"误判为"不支撑"——因为它们只读了 `sources.md` 的一行"主要内容"概括，而原始页面其实**逐字载明**这些断言。已由人工抓取推翻的实例：
- 农业电池"密闭车厢可达 80°C / 每单元≤4 个相隔 30cm / 浸泡 72 小时" —— SOURCE-036 官方原文即如此；
- Mini 电池"充满后静置 48 小时" —— SOURCE-003 官方新手攻略原文即如此；
- SOURCE-027 内容确为 DJI 官方保养手册（第三方镜像，非伪造）。

**结论**：知识库的"来源→正文"支撑关系总体良好、26 篇 synthetic 案例全部落地既有知识；真正的硬伤集中在监管分类、机型隔离与元数据一致性，已按上述修复。