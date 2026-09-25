---
document_id: drone_technical_gnss_positioning
document_type: technical
product_model: all
component: gnss
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-002","SOURCE-003","SOURCE-007","SOURCE-021","SOURCE-032","SOURCE-034"]
---

# 技术：GNSS / 卫星定位系统

> 本文介绍本知识库覆盖的各类无人机所采用的 GNSS 方案与定位精度。
> **注意：不同机型 GNSS 与精度不同，使用参数时务必对应型号，不可跨型号套用。**

## 各机型 GNSS 配置

| 机型 | GNSS 卫星系统 | 说明来源 |
|---|---|---|
| DJI Mini 4 Pro | GPS + Galileo + BeiDou | SOURCE-002 |
| DJI Matrice 350 RTK | GPS + GLONASS + BeiDou + Galileo | SOURCE-021 |
| DJI Mavic 3 Enterprise | GPS + Galileo + BeiDou + GLONASS；**GLONASS 仅在 RTK 模块开启时支持** | SOURCE-032 |
| DJI Agras T50（RTK） | GPS + GLONASS + BeiDou + Galileo + QZSS | SOURCE-034 |

## 定位精度对比

### DJI Mini 4 Pro（SOURCE-002）

- 悬停精度（视觉定位）：垂直 ±0.1 m，水平 ±0.1 m
- 悬停精度（GNSS）：垂直 ±0.5 m，水平 ±0.5 m
- 视觉定位在**暗光、水面/强反光、纯色/弱纹理、细小障碍物**环境下无法正常工作。（SOURCE-003）

### DJI Matrice 350 RTK（SOURCE-021）

- RTK 定位（RTK FIX）：水平 1 cm + 1 ppm；垂直 1.5 cm + 1 ppm
- 悬停精度：RTK 正常时垂直 ±0.1 m、水平 ±0.1 m；GNSS 正常时垂直 ±0.5 m、水平 ±1.5 m

### DJI Agras T50（SOURCE-034）

- RTK 悬停精度：水平 ±10 cm，垂直 ±10 cm
- 仿地定高范围 1.5–30 m，山地最大坡度 50°

## GPS 信号受扰导致的风险

- GPS 信号易受环境遮挡（建筑物、山体、树林）与电磁干扰（金属、高压塔、高压输电站、
  雷达站、移动通信基站、广播塔、Wi-Fi、蓝牙设备）影响。（SOURCE-007）
- 当 GPS 信号弱或指南针受干扰时，飞行器可能进入 **ATTI（姿态）模式**，
  无法定点悬停，应尽快在安全位置降落。（SOURCE-007）
- 开机后 GPS 搜星通常需要 1–3 分钟；在室外空旷处起飞可获得较好定位。（SOURCE-007）

## 售后知识主张

- 用户报"GPS 信号弱 / 无法定点 / 水平漂移"时，应优先判断是否为**环境遮挡或电磁干扰**
  （非硬件故障），按 GPS 排查 SOP 处理。
- 只有确认排除环境因素后仍异常，才考虑硬件送修（人工升级条件详见故障排查文档）。

## 来源

- SOURCE-002 / SOURCE-003 / SOURCE-007 / SOURCE-021 / SOURCE-032 / SOURCE-034