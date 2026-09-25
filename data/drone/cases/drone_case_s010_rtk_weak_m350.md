---
document_id: drone_case_s010_rtk_weak_m350
document_type: case
product_model: matrice_350_rtk
component: rtk
fault_type: rtk_signal_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-028"]
---

# 模拟案例 CASE-S010：行业机 RTK 信号差

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Matrice 350 RTK |
| case_type | synthetic |
| 用户描述 | 巡检中发现 App 提示"RTK 信号差"，但网络 RTK 显示已连接 |
| 已知条件 | 作业场地靠近山体/涵洞；曾从 D-RTK 2 基站切换到网络 RTK 未重启 |
| 可能原因 | 场景遮挡；基站/网络切换后未重启（SOURCE-028） |
| 建议排查 | 1) 换空旷场地测试；2) 检查差分源卫星数量；3) 切换差分源后重启设备（RTK 信号差故障文档） |
| 参考知识 | drone_troubleshooting_rtk_signal_weak / drone_technical_rtk_differential |
| 人工升级条件 | 空旷+重启后仍差 → 升级人工 |
| 来源 | SOURCE-028 |

> RTK 差优先查遮挡与差分源切换。