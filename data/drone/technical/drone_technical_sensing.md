---
document_id: drone_technical_sensing
document_type: technical
product_model: all
component: sensing
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-002","SOURCE-003","SOURCE-018","SOURCE-021","SOURCE-034"]
---

# 技术：感知与避障系统

无人机通过**视觉相机 + 红外 / 雷达**感知周边障碍物，用于避障与室内定位。
各机型感知硬件与能力不同，参数不可跨型号套用。

## 各机型感知配置

| 机型 | 感知方式 | 关键参数 | 来源 |
|---|---|---|---|
| Mini 4 Pro | 全向双目视觉 + 底部三维红外 | 前后/侧有效避障 ≤12 m/s；上下 ≤5 m/s；红外 0.1–8 m | SOURCE-002 |
| Matrice 350 RTK | 六向视觉 + 红外 | 视觉范围前后 0.7–40 m、上下 0.6–30 m；红外 0.1–8 m | SOURCE-021 |
| Agras T50 | 前/后相控阵雷达 + 双目视觉 | 全向避障 1–50 m，安全距离 2.5 m；双目 0.5–29 m | SOURCE-034 |

## 视觉定位 / 避障的已知限制（SOURCE-003、SOURCE-018）

DJI 官方明确：视觉定位在以下环境**无法正常工作**：

- 暗光场景；
- 水面 / 强反光表面；
- 纯色 / 弱纹理表面；
- 细小障碍物。

Matrice 350 RTK 视觉避障还需表面纹理丰富、光照 >15 lux。（SOURCE-021）

## 售后知识主张

- 用户在**未起飞 / 低空室内**出现"漂移 / 无法悬停"，很可能因视觉定位失效，
  应引导其到**光线充足、有纹理、空旷**环境重试，而非直接判定硬件故障。
- 运动挡（S 挡）下视觉避障自动关闭，飞行距离密切——这是**功能设计**而非故障。（见飞行模式技术文）

## 来源

- SOURCE-002 / SOURCE-003 / SOURCE-018 / SOURCE-021 / SOURCE-034