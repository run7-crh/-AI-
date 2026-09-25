---
document_id: drone_case_s011_network_rtk
document_type: case
product_model: matrice_350_rtk
component: rtk
fault_type: rtk_signal_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-022","SOURCE-029"]
---

# 模拟案例 CASE-S011：网络 RTK 服务不可用

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Matrice 350 RTK |
| case_type | synthetic |
| 用户描述 | 网络 RTK 突然不可用，提示信号弱 |
| 已知条件 | 网络 RTK 服务已购买但可能过期；当前处于偏远山区网络差 |
| 可能原因 | 服务未开启/已过期；无网络 RTK 服务；网络环境不可用（SOURCE-029） |
| 建议排查 | 1) 检查服务是否开启；2) 检查有效期，过期续购；3) 检查网络；无服务则改用 RTK 移动站（网络 RTK 弱排查故障文档） |
| 参考知识 | drone_troubleshooting_rtk_signal_weak / drone_technical_rtk_differential |
| 人工升级条件 | 服务/网络无误仍不可用 → 升级人工 |
| 来源 | SOURCE-022 / SOURCE-029 |

> 注意：网络 RTK 中国区前两年免费，第三年起收费（SOURCE-022），是过期常见原因。