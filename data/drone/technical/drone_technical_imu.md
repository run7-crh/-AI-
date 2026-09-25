---
document_id: drone_technical_imu
document_type: technical
product_model: mini_4_pro
component: imu
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-009"]
---

# 技术：IMU（惯性测量单元）与校准

## 原理

IMU（Inertial Measurement Unit）融合加速度计与陀螺仪，是飞行器感知**姿态与加速度**的核心。
IMU 数据出现偏差时，DJI Fly 会提示进行 IMU 校准。（SOURCE-009）

## 触发条件

- App 提示需要进行 IMU 校准；
- IMU 校准失败或无法校准（常见于数据偏差）。

## 校准方法（DJI Fly）（SOURCE-009）

> 前置：安装 DJI Fly，飞行器与遥控器已连接；电量 ≥ **50%**；飞行器置于**水平干燥**位置。

1. 打开 DJI Fly 飞行界面，进入 `··· > 安全 > 传感器状态 > IMU > 校准`。
2. 按页面提示**摆放飞行器**（涉及水平、竖立、倒置等多姿态，具体以界面为准）。
3. 校准失败：重启飞行器后再试；仍无法解决则申请自助寄修。

## 售后知识主张

IMU 校准不需要户外，只需水平静止平台；与指南针（需空旷避开磁场）是**两个不同校准**。
用户混淆两者时，应引导其分别按对应 SOP 处理。

## 来源

- SOURCE-009：DJI 官方 IMU 校准操作指南