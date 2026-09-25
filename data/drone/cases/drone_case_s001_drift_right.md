---
document_id: drone_case_s001_drift_right
document_type: case
product_model: mini_4_pro
component: compass
fault_type: compass_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-007","SOURCE-008"]
---

# 模拟案例 CASE-S001：起飞后持续向右偏移

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | **synthetic**（本案例为基于官方资料构造的模拟场景，非真实用户售后工单） |
| 用户描述 | 无人机起飞后持续向右偏移，无法稳定直线飞行；App 提示过指南针需校准 |
| 已知条件 | 起飞点位于建筑密集区/停车场附近；昨天下载了最新固件并完成对频 |
| 可能原因 | 指南针（罗盘）受磁场/大型金属干扰（SOURCE-008）；或 GPS 弱导致航向基准偏差（SOURCE-007） |
| 建议排查 | 1) 移到空旷无磁场/金属场地；2) 按指南针校准 SOP 重新校准；3) 若仍异常检查 GPS 环境（GPS 排查 SOP） |
| 参考知识 | drone_sop_compass_calibration / drone_technical_compass / drone_sop_gps_troubleshoot |
| 人工升级条件 | 空旷环境两次校准仍失败 → 升级人工寄修检测 |
| 来源 | SOURCE-008 / SOURCE-007 |

> 说明：本案例仅用于测试 Agent"识别故障→检索知识→给出有依据排查建议"的能力，不构成真实售后数据。