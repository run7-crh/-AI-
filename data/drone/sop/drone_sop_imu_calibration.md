---
document_id: drone_sop_imu_calibration
document_type: sop
product_model: mini_4_pro
component: imu
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-009"]
---

# SOP：IMU 校准

## SOP 名称

IMU 校准流程

## 适用条件

App 提示需要 IMU 校准，或 IMU 校准失败/数据偏差时。（SOURCE-009）

## 前置条件

- 电量 ≥ **50%**；飞行器与遥控器已连接；置于**水平干燥**位置。

## 操作步骤

1. DJI Fly 飞行界面：`··· > 安全 > 传感器状态 > IMU > 校准`。（SOURCE-009）
2. 按页面提示**摆放飞行器**（涉及水平/竖立/倒置等多姿态，具体以界面为准）。（SOURCE-009）
3. 校准过程保持机身稳定、勿触碰。（SOURCE-009）
4. 校准失败：**重启飞行器后再试**。（SOURCE-009）

## 检查结果

校准完成 = App 不再提示需 IMU 校准，姿态数据正常。

## 异常情况

- 多次校准失败、重启后仍无法完成。

## 停止操作条件

- IMU 校准失败且重启后仍失败时，暂缓飞行，先处理。

## 人工升级条件

- 重启后仍无法完成 IMU 校准 → 升级人工寄修。

## 来源

- SOURCE-009