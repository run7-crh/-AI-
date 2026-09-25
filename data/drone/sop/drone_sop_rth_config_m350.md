---
document_id: drone_sop_rth_config_m350
document_type: sop
product_model: matrice_350_rtk
component: flight_mode
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-025"]
---

# SOP：返航（RTH）设置与执行（Matrice 350 RTK）

> 本 SOP 仅适用于 **Matrice 350 RTK**（DJI Pilot 2 地面站）。
> 消费级机型（DJI Fly，如 Mini 4 Pro）返航逻辑与操作不同，见文档 **drone_sop_rth_config**。

## SOP 名称

Matrice 350 RTK 返航参数设置与自动返航处置

## 适用条件

M350 RTK 每次起飞前配置返航；飞行中需要主动/被动返航时。（SOURCE-025）

## 前置条件

- 起飞点开阔、GNSS 定位正常，可记录返航点；信号/定位良好时才能记录返航点。

## 操作步骤

1. **设置返航**：在 DJI Pilot 2 中进入安全设置，配置 RTH 参数（返回高度、返航模式）。（SOURCE-025）
2. **设置返航高度**：观察周围障碍物，将 RTH 返回高度设置为**高于障碍物高度**。（SOURCE-025）
3. **主动返航（Smart RTH）**：通过遥控器返航键或 DJI Pilot 2 界面触发，飞行器按配置返回返航点。（SOURCE-025）
4. **低电量返航**：电量仅够返航时 App 提示并自动进入返航；返航中注意电量余量。（SOURCE-025）
5. **失控（Failsafe）返航**：图传/遥控信号丢失后，飞行器在确认超时后自动执行 Failsafe 返航。M350 RTK 规格注明信号丢失约 6 秒后自动启用 Failsafe RTH（SOURCE-025）。
6. **取消返航**：正常返航过程中可短按遥控器返航键暂停/取消；紧急情况下可使用**急停键**中断，需评估飞行状态与安全。（SOURCE-025）

## 检查结果

返航成功返回并降落在返航点附近。

## 异常情况

- 返航点未记录成功、返回高度不足、返航路径遇障碍或强烈磁/信号干扰。

## 停止操作条件

- 返航路径不清晰或信号持续丢失过久时，应优先保持监视并据实评估；涉及低电量/失控自动返航的取消操作需谨慎。

## 人工升级条件

- 返航功能失效（主动触发无响应）→ 升级人工；飞行中异常返航后务必记录飞行数据供分析。

## 来源

- SOURCE-025：Matrice 350 RTK 用户手册 v1.2（英文 PDF）