---
document_id: drone_troubleshooting_aircraft_disconnected
document_type: troubleshooting
product_model: mini_4_pro
component: remote_controller
fault_type: aircraft_disconnected
source_type: official
data_type: factual
source_id: ["SOURCE-013"]
---

# 故障：App 提示 Aircraft Disconnected / 未连接遥控器

## 适用范围

航拍无人机（DJI Mini 4 Pro 适用）（SOURCE-013）。

## 故障现象

- 打开 DJI Fly 提示"飞行器未连接"或"Aircraft not connected to RC"；
- 遥控器无法操作飞行器。

## 可能原因（官方）

- 飞行器与遥控器型号不匹配；
- 飞行器与遥控器固件版本不一致；
- 飞行器未与遥控器对频。

## 排查步骤（官方）

1. 确认飞行器与遥控器均开机，飞行器机臂指示灯亮起。
2. 确认 DJI Fly 为最新版本。
3. 若固件版本不一致，按 App 提示进入**固件更新界面**更新飞行器与遥控器；更新完成后飞行器自动重启。
4. 若飞行器指示灯**每两秒闪两次黄灯**、遥控器最左指示灯红灯或闪红 → 可能对频失败，
   参考 Aircraft Linking Guide（对频操作指南）**重新对频**。

## 处理建议

先核对固件版本一致性，再对频；型号不匹配则无法解决，需更换匹配设备。

## 安全注意事项

- 对频操作在空旷处进行，避免误触发。

## 人工升级条件

- 固件一致且重新对频后仍无法连接 → 升级人工，提供指示灯状态信息。

## 来源

- SOURCE-013