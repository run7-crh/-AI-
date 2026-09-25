---
document_id: drone_case_s022_agri_license
document_type: case
product_model: agras_t50
component: regulatory
fault_type: compliance
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-045","SOURCE-046"]
---

# 模拟案例 CASE-S022：农用机是否需操控员执照

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Agras T50（中型） |
| case_type | synthetic |
| 用户描述 | 农民问操作 T50 要不要考执照 |
| 已知条件 | 在农林牧渔区域适飞空域内作业 |
| 可能原因/结论 | 大中型无人机需操控员执照，但**常规农用例外**：中型及以下农用机在农林牧渔区域适飞空域作业无需执照，需生产者培训取得**操作证书**（SOURCE-045、SOURCE-046） |
| 建议排查 | 1) 明确区分"登记"（仍需 UOM 实名登记）与"执照/操作证书"；2) 非农用场景则按大中型要求；3) 具体以最新办事指南为准 |
| 参考知识 | drone_safety_caac_compliance / drone_safety_agri_operation |
| 人工升级条件 | 涉及非农用/跨区/特定空域 → 升级人工/官方咨询 |
| 来源 | SOURCE-045 / SOURCE-046 |

> "农用免执照但需操作证书、仍需登记、免飞行申请"是最易混淆的组合，Agent 需准确区分。