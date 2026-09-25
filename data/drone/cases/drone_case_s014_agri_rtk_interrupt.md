---
document_id: drone_case_s014_agri_rtk_interrupt
document_type: case
product_model: agras_t50
component: rtk
fault_type: rtk_signal_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-029","SOURCE-034"]
---

# 模拟案例 CASE-S014：农业作业中途 RTK 定位中断

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Agras T50 |
| case_type | synthetic |
| 用户描述 | 喷药作业途中 App 提示 RTK 定位异常，航线偏移 |
| 已知条件 | 作业地块边缘有高大树木；当天多云且地块偏远网络差 |
| 可能原因 | RTK 信号受遮挡 / 网络差分不稳定（SOURCE-034、SOURCE-029） |
| 建议排查 | 1) 立即暂停作业并降落，避免误喷/漏喷；2) 检查差分源（网络/基站）与网络；3) 换无障碍开阔处确认 RTK FIX 后再继续；或改用 RTK 移动站 |
| 参考知识 | drone_safety_agri_operation / drone_technical_rtk_differential |
| 人工升级条件 | 排除遮挡/差分源后仍中断 → 升级人工 |
| 来源 | SOURCE-034 / SOURCE-029 |

> 农用作业定位中断风险高，先停再查，避免药液误施。