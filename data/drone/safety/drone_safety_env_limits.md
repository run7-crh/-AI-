---
document_id: drone_safety_env_limits
document_type: safety
product_model: all
component: flight_safety
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-002","SOURCE-007","SOURCE-021","SOURCE-022","SOURCE-034"]
---

# 安全：环境限制与作业边界

## 工作温度范围（来源）

| 机型 | 工作温度 | 来源 |
|---|---|---|
| DJI Mini 4 Pro | -10°C 至 40°C | SOURCE-002 |
| DJI Matrice 350 RTK | -20°C 至 50°C | SOURCE-021 |
| DJI Agras T50（遥控器 RC Plus） | -20°C 至 50°C | SOURCE-034 |

## 抗风与海拔（来源）

| 机型 | 最大抗风 | 最大海拔 | 来源 |
|---|---|---|---|
| Mini 4 Pro | 10.7 m/s（5 级风） | 4000 m（标准电池） | SOURCE-002 |
| Matrice 350 RTK | 12 m/s | 5000 m / 7000 m（高原桨） | SOURCE-021 |

## 天气与恶劣环境

- **雨天**：Matrice 350 RTK 不建议在 >100 mm/24 小时雨量下飞行。（SOURCE-022）
- **磁场/金属环境**：影响指南针，详见指南针技术文档。
- GPS 弱 + 指南针受扰时，飞行器可能进入 ATTI 模式 → 尽快降落。（SOURCE-007）

## 售后知识主张

- 用户报"抗风不足/高处性能下降"时，先对照机型温度、海拔、抗风限制，判断是否为**环境影响**而非故障。
- 超限环境（低温电池性能下降、高温、强风、雨雪）应作为**边界条件**提示用户，而非直接判定损坏。

## 人工升级条件

- 在机型限制范围内仍出现持续性能异常 → 升级人工；超限使用导致的异常应单独说明。

## 来源

- SOURCE-002 / SOURCE-007 / SOURCE-021 / SOURCE-022 / SOURCE-034