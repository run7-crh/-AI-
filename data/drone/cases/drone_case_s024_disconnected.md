---
document_id: drone_case_s024_disconnected
document_type: case
product_model: mini_4_pro
component: remote_controller
fault_type: aircraft_disconnected
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-013"]
---

# 模拟案例 CASE-S024：升级后 App 提示 Aircraft Disconnected

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 只给飞行器升级了固件、没升遥控器，之后 App 提示飞行器未连接 |
| 已知条件 | 飞行器与遥控器固件版本不一致 |
| 可能原因 | 飞行器与遥控器**固件版本不一致**，导致连接失败（SOURCE-013） |
| 建议排查 | 1) 用最新 DJI Fly 同时升级飞行器与遥控器（SOURCE-013）；2) 升级完成自动重启后再连接；3) 若指示灯异常再重新对频 |
| 参考知识 | drone_troubleshooting_aircraft_disconnected / drone_technical_firmware |
| 人工升级条件 | 固件统一后仍无法连接 → 升级人工 |
| 来源 | SOURCE-013 |

> 部分升级是"未连接"的常见原因，提示先核对固件一致性。