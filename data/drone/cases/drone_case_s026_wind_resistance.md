---
document_id: drone_case_s026_wind_resistance
document_type: case
product_model: mini_4_pro
component: flight_mode
fault_type: environmental_impact
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-002"]
---

# 模拟案例 CASE-S026：大风天飞行报警 / 抗风不足

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 风大那天飞行，App 多次警告抗风不足，飞行姿态不稳 |
| 已知条件 | 当天风速超过机型抗风等级 |
| 可能原因 | 超过最大抗风 **10.7 m/s（5 级风）**（SOURCE-002），属**环境边界**非故障 |
| 建议排查 | 1) 对照抗风等级确认是否超限（SOURCE-002）；2) 强风下立即降低飞行或降落返航；3) 保留高度与电量余量 |
| 参考知识 | drone_safety_env_limits / drone_safety_abnormal_flight |
| 人工升级条件 | 风速在限制内仍姿态异常 → 升级人工 |
| 来源 | SOURCE-002 |

> 抗风不足是机型能力边界，提示用户规避，而非上报故障。