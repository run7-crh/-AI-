---
document_id: drone_case_s002_gps_weak
document_type: case
product_model: mini_4_pro
component: gnss
fault_type: gps_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-007"]
---

# 模拟案例 CASE-S002：GPS 信号弱无法定点悬停

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 在小区楼下起飞，App 一直提示 GPS 信号弱，飞行器水平漂移无法定点 |
| 已知条件 | 楼间距窄、四周高楼环绕；附近有 Wi-Fi 密集（多户路由器） |
| 可能原因 | 上方/四周遮挡（高楼）+ 电磁干扰（Wi-Fi 路由器/基站）导致 GPS 搜星不足（SOURCE-007） |
| 建议排查 | 1) 等待搜星 1-3 分钟；2) 转至室外空旷处起飞；3) 远离建筑与电磁干扰源（GPS 排查 SOP） |
| 参考知识 | drone_sop_gps_troubleshoot / drone_technical_gnss_positioning |
| 人工升级条件 | 空旷处仍无法定位 → 升级人工寄修 |
| 来源 | SOURCE-007 |

> 判断要点：多为环境因素，先环境后硬件。