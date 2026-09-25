---
document_id: drone_case_s015_agri_battery_corrosion
document_type: case
product_model: agras_t50
component: battery
fault_type: battery_charging_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-036"]
---

# 模拟案例 CASE-S015：农业电池插头腐蚀后无法充电

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Agras T50 |
| case_type | synthetic |
| 用户描述 | 作业结束几天后电池无法充电，插头有绿色腐蚀物 |
| 已知条件 | 作业后未擦干电池插头农药、未盖盖帽 |
| 可能原因 | 农药残留腐蚀电源插头，可能导致短路自燃（SOURCE-036） |
| 建议排查 | 1) 立即停止充电/使用该电池；2) 检查插头腐蚀程度，不要强行充电；3) 今后作业后用干布擦干并盖插头盖帽（农业电池 SOP） |
| 参考知识 | drone_sop_agri_battery_safe / drone_safety_agri_operation / drone_troubleshooting_battery_swelling |
| 人工升级条件 | 电池腐蚀/无法充电 → 升级人工，禁止继续使用并更换 |
| 来源 | SOURCE-036 |

> 提示：农药防腐是农业电池最高优先级保养项，腐蚀可能致短路自燃。