---
document_id: drone_sop_rth_config
document_type: sop
product_model: mini_4_pro
component: flight_mode
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-010","SOURCE-016"]
---

# SOP：返航（RTH）设置与执行

> 本 SOP 适用于使用 **DJI Fly** App 的消费级机型（如 DJI Mini 4 Pro）。
> 行业级机型（Matrice 350 RTK）返航逻辑与操作不同，见独立文档 **drone_sop_rth_config_m350**。

## SOP 名称

返航参数设置与自动返航处置

## 适用条件

每次起飞装机前配置返航；飞行中需要主动/被动返航时。（SOURCE-010、SOURCE-016）

## 前置条件

- 起飞点开阔、可记录返航点；信号/定位良好时才能记录返航点。

## 操作步骤

1. **设置丢失返航**：将"遥控器信号丢失"设置为 **RTH**（DJI Fly：三点菜单 → 安全 → 安全高级设置 → 信号丢失 → RTH）。（SOURCE-016）
2. **设置返航高度**：观察周围障碍物，将 RTH 高度设置为**高于障碍物高度**。（SOURCE-016）
3. **主动返航**：长按遥控器 RTH 键，或在 DJI Fly 相机界面长按返航图标。（SOURCE-010）
4. **低电量返航**：电量仅够返航时 App 提示；未确认则自动进入低电量返航；仅够降落时强制下降且不可取消。（SOURCE-010）
5. **失控返航**：信号丢失且设置为 RTH 时自动触发。（SOURCE-010）

## 检查结果

返航成功返回并降落在返航点附近。

## 异常情况

- 返航点未记录成功、返航高度不足、返航路径遇障碍或强烈磁/信号干扰。

## 停止操作条件

- 返航路径不清晰或信号持续丢失过久时，应优先保持视距监视并据实评估。

## 人工升级条件

- 返航功能失效（主动触发无响应）→ 升级人工；飞行中异常返航后务必记录飞行数据供分析。

## 来源

- SOURCE-010 / SOURCE-016