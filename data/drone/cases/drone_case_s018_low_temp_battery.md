---
document_id: drone_case_s018_low_temp_battery
document_type: case
product_model: mini_4_pro
component: battery
fault_type: environmental_impact
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-002"]
---

# 模拟案例 CASE-S018：低温环境下电池续航骤降

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 冬天 0°C 起飞，电量掉得很快，续航明显变短 |
| 已知条件 | 环境温度接近下限；充电在常温完成 |
| 可能原因 | 低温使电池放电性能下降，接近工作下限（-10°C）性能衰减（SOURCE-002）；属**环境影响**非故障 |
| 建议排查 | 1) 对照机型工作温度范围确认是否超限（SOURCE-002）；2) 建议低温下缩短单次飞行时间、保留电量余量；3) 电池保暖存放 |
| 参考知识 | drone_safety_env_limits / drone_technical_smart_battery |
| 人工升级条件 | 常温范围内仍异常衰减 → 升级人工 |
| 来源 | SOURCE-002 |

> 低温续航下降是电池固有特性，应作为边界条件提示而非误判故障。