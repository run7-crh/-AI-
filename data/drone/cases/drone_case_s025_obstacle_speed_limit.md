---
document_id: drone_case_s025_obstacle_speed_limit
document_type: case
product_model: mini_4_pro
component: sensing
fault_type: vision_resolution_limit
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-002","SOURCE-017"]
---

# 模拟案例 CASE-S025：高速贴线飞行未触发避障

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 快速贴着一排树飞行时没有避障，质疑避障失效 |
| 已知条件 | 飞行速度接近运动挡；侧方向贴近树冠 |
| 可能原因 | 侧视避障有效速度 ≤12 m/s、且需满足感知距离，超速或侧面快速接近时避障可能来不及介入（SOURCE-002）；S 挡下避障自动关闭（SOURCE-017） |
| 建议排查 | 1) 核对飞行速度与挡位（SOURCE-017）；2) 说明避障对速度/环境的局限（SOURCE-002）；3) 建议 N 挡低速、保持安全距离 |
| 参考知识 | drone_technical_sensing / drone_technical_flight_modes / drone_safety_flight_basics |
| 人工升级条件 | 低速+良好环境仍无预警 → 升级人工 |
| 来源 | SOURCE-002 / SOURCE-017 |

> 避障有速度与感知距离边界，需正确向用户解释，避免误报"功能失效"。