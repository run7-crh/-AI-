---
document_id: drone_case_s020_indoor_drift
document_type: case
product_model: mini_4_pro
component: sensing
fault_type: vision_resolution_limit
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-003","SOURCE-018"]
---

# 模拟案例 CASE-S020：室内起飞后漂移

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 在客厅暗光、地面反光的瓷砖上起飞，飞行器左右漂移 |
| 已知条件 | 室内无 GPS；地面纯色反光瓷砖；灯光较暗 |
| 可能原因 | 视觉定位在暗光/强反光/纯色弱纹理环境下无法正常工作（SOURCE-003、SOURCE-018） |
| 建议排查 | 1) 说明此为视觉定位固有局限非故障；2) 建议在有纹理、光线充足的环境飞行；3) 室内飞行保持低空低速、视距控制 |
| 参考知识 | drone_technical_sensing / drone_safety_flight_basics |
| 人工升级条件 | 良好环境仍无法悬停 → 升级人工 |
| 来源 | SOURCE-003 / SOURCE-018 |

> 演示 Agent 识别"视觉定位环境限制"而非上报故障。