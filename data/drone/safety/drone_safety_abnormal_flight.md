---
document_id: drone_safety_abnormal_flight
document_type: safety
product_model: all
component: flight_safety
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-007","SOURCE-010","SOURCE-012","SOURCE-016"]
---

# 安全：异常飞行与遇险处理

## ATTI（姿态）模式风险（SOURCE-007）

- GPS 信号弱或指南针受干扰时，飞行器可能进入 **ATTI（姿态）模式**。
- ATTI 模式下**无法定点悬停**，应尽快在**安全位置降落**。

## 图传与遥控中断（SOURCE-012、SOURCE-010）

- 飞行中画面卡住/图传丢失：打杆将飞行器**上升到超过障碍物高度**，图传可能恢复。（SOURCE-012）
- 已设置"信号丢失=返航"时，失控会自动触发返航。（SOURCE-010、SOURCE-016）
- 返航默认触发方式可见返航 SOP。

## 低电量处置（SOURCE-010）

- 电量仅够返航时 App 会提示/自动返航；仅够降落时**强制下降**且不可取消。
- 起飞前确保电量充足、返航/备降点可行。

## 遇险处置原则（基于官方安全指引，SOURCE-016）

1. 保持冷静，优先**确保飞行器与人员安全**，不盲目猛打杆。
2. 优先让飞行器**回到视距内 / 触发返航**。
3. 若失控，记录位置并启动官方找回/售后流程，保留飞行数据（录屏、日志）用于分析。

## 人工升级条件

- 发生坠机/丢失/异常返航 → 升级人工；提供飞行数据、录像、发生时间与环境，配合官方分析。

## 来源

- SOURCE-007 / SOURCE-010 / SOURCE-012 / SOURCE-016