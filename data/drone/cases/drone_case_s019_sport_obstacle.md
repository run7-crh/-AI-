---
document_id: drone_case_s019_sport_obstacle
document_type: case
product_model: mini_4_pro
component: flight_mode
fault_type: flight_mode_misuse
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-017"]
---

# 模拟案例 CASE-S019：运动挡不避障撞树投诉

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 用运动挡(S)高速飞行时撞到树枝，投诉"避障失效" |
| 已知条件 | 遥控器处于 S 挡 |
| 可能原因 | **S 挡会关闭视觉避障**，这是官方设计行为，非故障（SOURCE-017） |
| 建议排查 | 1) 向用户说明 S 挡关闭避障的设计（SOURCE-017）；2) 建议降速/使用 N 挡以获得避障；3) 损坏评估走售后 |
| 参考知识 | drone_technical_flight_modes / drone_safety_abnormal_flight / drone_safety_flight_basics |
| 人工升级条件 | 撞机造成损伤需评估 → 引导售后，不判定"避障故障" |
| 来源 | SOURCE-017 |

> 这属于用户误用挡位而非产品缺陷，售后需正确归因。