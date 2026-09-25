---
document_id: drone_technical_rtk_differential
document_type: technical
product_model: matrice_350_rtk
component: rtk
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-021","SOURCE-022","SOURCE-028","SOURCE-029","SOURCE-034","SOURCE-039"]
---

# 技术：RTK 实时差分定位

## 概述

RTK（Real-Time Kinematic）通过基准站 / 网络差分服务为无人机提供**厘米级**定位，
用于行业测绘、农业精量作业等对精度要求高的场景。本知识库覆盖的 RTK 机型为
**Matrice 350 RTK** 与 **Agras T50**。

> 本文属**跨机型**技术文，同时覆盖 M350 RTK 与 Agras T50；引用内容时请按各小节机型取段，
> 勿用 M350 的 D-RTK 2 / 网络 RTK 参数套用到 T50。frontmatter 的 product_model 以 Matrice 350 RTK 为主。

## Matrice 350 RTK 的 RTK 获取方式（SOURCE-022）

### 1. D-RTK 2 移动站

- 通过 DJI Pilot 2 地面站 App 设置连接 D-RTK 2 移动站。
- 支持 RTCM3.2 协议；**一个 D-RTK 2 移动站可同时用于多台 Matrice 350 RTK**。

### 2. 网络 RTK

- 遥控器通过 4G 网卡或 Wi-Fi 热点连接网络 RTK 服务，支持 RTCM3.2。
- 中国区网络 RTK 服务前两年免费，**第三年起需单独购买**。

### 3. 自定义网络 RTK

- 基于 NTRIP 协议，支持 RTCM3.0 / RTCM3.1 / RTCM3.2。

### 精度

- RTK FIX 状态：水平 1 cm + 1 ppm；垂直 1.5 cm + 1 ppm。（SOURCE-021）

## RTK 信号差的常见原因与处理（SOURCE-028）

| 原因 | 处理 |
|---|---|
| 使用场景有遮挡（建筑/山体） | 更换到空旷无遮挡场地测试 |
| D-RTK 2 移动站接收卫星数量不足 | 检查移动站下卫星数量，可更换场地 |
| 网络 RTK 与 D-RTK 2 直接切换后未重启 | 从基站切换到网络 RTK（或反之）后需**重启设备** |

## 网络 RTK 信号弱的排查（SOURCE-029）

1. 检查网络 RTK 服务是否已开启。
2. 检查服务有效期，过期后需重新购买。
3. 检查网络环境；若无网络 RTK 服务，建议改用 RTK 移动站或到网络信号强区域。

## Agras T50 的 RTK（SOURCE-034）

- RTK 悬停精度：水平 ±10 cm，垂直 ±10 cm。
- RTK 频段：GPS L1/L2、GLONASS F1/F2、BeiDou B1I/B2I/B3I、Galileo E1/E5b、QZSS L1/L2。
- 农业作业常配合"智能补给点/中断点"等辅助点实现精量作业。（SOURCE-039）

## 售后知识主张

- 用户报"RTK 信号差 / 开机连接 RTK 报警"时，**先排除遮挡与差分源切换两大原因**，
  再判断是否需重启，最后才考虑硬件。
- RTK 与停车场/钢筋建筑等场景无关——那是**指南针/磁场**问题，勿混为一谈（见指南针技术文）。

## 来源

- SOURCE-021 / SOURCE-022 / SOURCE-028 / SOURCE-029 / SOURCE-034 / SOURCE-039