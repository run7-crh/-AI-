---
document_id: drone_case_s013_vision_calibration_m350
document_type: case
product_model: matrice_350_rtk
component: sensing
fault_type: vision_calibration
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-025"]
---

# 模拟案例 CASE-S013：行业机视觉系统需重新校准

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Matrice 350 RTK |
| case_type | synthetic |
| 用户描述 | 一次轻微磕碰后，DJI Pilot 2 提示视觉系统需要重新校准 |
| 已知条件 | 经历较弱碰撞；环境温度近期变化大 |
| 可能原因 | 视觉系统出厂已校准，受碰撞/温差变化后需重校（SOURCE-025） |
| 建议排查 | 1) 用 USB-C 连接调参接口至电脑；2) 打开 DJI Assistant 2（行业系列）；3) 按界面执行视觉校准（视觉校准故障文档） |
| 参考知识 | drone_troubleshooting_vision_calibration / drone_technical_sensing |
| 人工升级条件 | 校准后仍提示异常 → 升级人工寄修 |
| 来源 | SOURCE-025 |

> 行业机视觉校准需通过行业专用调参软件完成。