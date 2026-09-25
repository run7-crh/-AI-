---
document_id: drone_technical_flight_modes
document_type: technical
product_model: all
component: flight_mode
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-002","SOURCE-010","SOURCE-016","SOURCE-017","SOURCE-025"]
---

# 技术：飞行挡位与返航（RTH）逻辑

## 遥控器挡位（DJI Mini 系列，SOURCE-017）

| 挡位 | 名称 | 限制与用途 |
|---|---|---|
| C 挡 | 平稳挡 | 限制最大飞行/上升/下降速度，拍摄更稳定 |
| N 挡 | 普通挡 | 推荐默认；GNSS + 视觉/红外实现精确悬停与智能功能 |
| S 挡 | 运动挡 | 速度最快，**视觉避障自动关闭** |

速限（Mini 4 Pro）见产品文档：C/N 12 m/s，S 16 m/s。（SOURCE-002）

## 返航（RTH）逻辑（SOURCE-010、SOURCE-025）

DJI 官方定义三种触发：

1. **主动返航（Smart RTH）**：长按遥控器 RTH 键，或在 DJI Fly 相机界面长按返航图标。
2. **低电量返航（Low Battery RTH）**：电量仅够返航时 App 提示；未确认/未及时选择
   则自动进入低电量返航；电量仅够降落时**强制下降且不可取消**。
3. **失控返航（Failsafe RTH）**：遥控信号丢失设置为"返航"时触发。

### 原路返航（SOURCE-010）

不满足视觉条件时：返航距离 >50 m 沿历史路径反向飞 50 m；5–50 m 直线飞回；≤5 m 直接降落。

### Matrice 350 RTK 的 Failsafe RTH（SOURCE-025）

- 遥控器信号丢失**超过 6 秒**自动启用，含"原路返航 + 智能返航"两阶段，
  最多沿原航线飞回 50 m 后尝试重连遥控器。
- 低电量返航：DJI Pilot 2 提示，10 秒内未操作则自动返航；返航中可短按智能返航键或急停键取消。

## 安全设置要点（SOURCE-016）

- 建议将"遥控器信号丢失"设置为 **RTH**。
- 将 **RTH 高度**设置为高于周围障碍物高度。

## 售后知识主张

- 用户抱怨"S 挡下不避障/撞机"，是**设计行为**（运动挡关闭视觉避障），需提前告知。
- "低电量强制下降"无法取消，是**安全功能**而非故障。
-："ATTI 模式"（GPS 弱或指南针受扰）下无法定点，应引导尽快降落。

## 来源

- SOURCE-002 / SOURCE-010 / SOURCE-016 / SOURCE-017 / SOURCE-025