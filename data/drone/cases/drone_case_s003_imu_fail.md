---
document_id: drone_case_s003_imu_fail
document_type: case
product_model: mini_4_pro
component: imu
fault_type: imu_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-009"]
---

# 模拟案例 CASE-S003：App 提示需 IMU 校准

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 开机电量 40%，App 提示需要 IMU 校准，尝试进入却提示校准失败 |
| 已知条件 | 电量偏低；放置于有斜度的桌面 |
| 可能原因 | IMU 数据偏差；电量 <50% 可能影响完成度；非水平静止平台（SOURCE-009） |
| 建议排查 | 1) 把电池充电到 ≥50%；2) 置于水平干燥平台；3) 按 IMU 校准 SOP 重试；4) 失败则重启飞行器再试 |
| 参考知识 | drone_sop_imu_calibration / drone_technical_imu |
| 人工升级条件 | 重启后仍无法完成 → 升级人工寄修 |
| 来源 | SOURCE-009 |

> 提示：IMU 校准与指南针校准是两个不同流程，勿混淆。