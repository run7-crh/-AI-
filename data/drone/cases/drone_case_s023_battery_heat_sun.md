---
document_id: drone_case_s023_battery_heat_sun
document_type: case
product_model: agras_t50
component: battery
fault_type: thermal_hazard
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-034","SOURCE-036"]
---

# 模拟案例 CASE-S023：高温暴晒后电池发热

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Agras T50 |
| case_type | synthetic |
| 用户描述 | 把电池放在密闭皮卡车厢里暴晒后，取出来发现很烫 |
| 已知条件 | 夏天地面高温，车厢密闭暴晒 |
| 可能原因 | 密闭车厢直射处温度可达约 **80°C**，电池可能因高温燃烧（SOURCE-036） |
| 建议排查 | 1) 立即将电池移到阴凉通风处，勿立即充电；2) 电芯温度需回落到快充范围（15°C–70°C）再充（SOURCE-034）；3) 检查有无鼓包/变形，如有则停用处理 |
| 参考知识 | drone_safety_battery / drone_sop_agri_battery_safe / drone_safety_agri_operation |
| 人工升级条件 | 电池过热/变形/疑似燃烧 → 立即升级人工并安全处置 |
| 来源 | SOURCE-036 / SOURCE-034 |

> 高温暴晒是农业电池重要危险源，避免阳光直射是官方明确要求。