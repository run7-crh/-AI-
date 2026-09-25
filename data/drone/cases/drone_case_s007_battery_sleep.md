---
document_id: drone_case_s007_battery_sleep
document_type: case
product_model: mini_4_pro
component: battery
fault_type: battery_charging_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-003","SOURCE-005"]
---

# 模拟案例 CASE-S007：新电池无法开机激活

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 新买的智能飞行电池插上主机无法开机，怀疑电池坏了 |
| 已知条件 | 电池为新品，出厂状态未充电 |
| 可能原因 | 出厂进入休眠模式以保运输安全，需先充电唤醒（SOURCE-005） |
| 建议排查 | 1) 放入机身/充电管家，用 30W PD 充电器充电唤醒（SOURCE-005）；2) 唤醒后短按+长按开机（SOURCE-003） |
| 参考知识 | drone_troubleshooting_battery_not_charging / drone_sop_battery_check |
| 人工升级条件 | 多次充电仍无法唤醒 → 升级人工 |
| 来源 | SOURCE-003 / SOURCE-005 |

> 新电池"不工作"多为休眠未唤醒，不要误判为故障。