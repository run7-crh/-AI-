---
document_id: drone_technical_transmission
document_type: technical
product_model: all
component: transmission
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-002","SOURCE-011","SOURCE-012","SOURCE-016","SOURCE-021"]
---

# 技术：图传与遥控通信链路

飞行器与遥控器之间的数据链路承载**控制指令 + 图传画面**。不同机型采用的方案、
频段、距离与天线数量不同，参数不可跨型号套用。

## 各机型图传方案

| 机型 | 图传方案 | 天线 | 来源 |
|---|---|---|---|
| DJI Mini 4 Pro | DJI O4 | 四天线，两发四收 | SOURCE-002 |
| DJI Matrice 350 RTK | DJI O3 图传行业版 | 四根图传天线，两发四收 | SOURCE-021 |

## DJI Mini 4 Pro（SOURCE-002）

- 工作频段：2.4000–2.4835 GHz；5.170–5.250 GHz；5.725–5.850 GHz。
- 最大信号有效距离（无遮挡、无干扰）：**FCC 20 km；CE/SRRC/MIC 10 km**。
- 有干扰环境距离大幅缩水（都市中心约 1.5–4 km）。
- 最低延时：飞行器+遥控器约 **120 ms**。

## DJI Matrice 350 RTK（SOURCE-021）

- 工作频段：飞行器 2.4 / 5.15–5.25 / 5.725–5.85 GHz；遥控器 2.4 / 5.725–5.85 GHz。
- 最大信号距离：**20 km（FCC）/ 8 km（CE/SRRC/MIC）**，无遮挡无干扰。

## 信号弱的环境因素（SOURCE-011、SOURCE-012）

- **遮挡物**（建筑、山体、树林）会显著衰减信号。
- **无线干扰源**（Wi-Fi、基站、广播塔、2.4G/5.8G 密集区）造成同频干扰。
- **遥控器天线朝向**未对准飞行器会降低接收。
- 特许：MicroSD 卡不兼容/损坏、移动设备不兼容也可能导致"无图传/黑屏"。（SOURCE-011）

## 售后知识主张

- "图传变差/断连"应先考虑**环境遮挡或干扰、天线朝向**，而非硬件故障。
- 官方建议将"遥控器信号丢失"设置为 **RTH**，断连时自动返航，降低丢失风险。（SOURCE-016）
- 确认频道干扰：App 选择"自动选择"信道，或变更飞行环境。（SOURCE-011）

## 来源

- SOURCE-002 / SOURCE-011 / SOURCE-012 / SOURCE-016 / SOURCE-021