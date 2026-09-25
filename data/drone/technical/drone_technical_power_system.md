---
document_id: drone_technical_power_system
document_type: technical
product_model: all
component: motors
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-002","SOURCE-006","SOURCE-021","SOURCE-022","SOURCE-032","SOURCE-034"]
---

# 技术：动力系统（电机 / 桨叶 / 载荷）

动力系统决定推力、载荷与抗风能力。各机型电机数量、桨叶型号、载荷上限差异显著，
**参数不可跨型号套用**。

## 各机型动力与载荷概览

| 机型 | 动力结构 | 桨叶 | 最大载荷/起飞重量 | 来源 |
|---|---|---|---|---|
| Mini 4 Pro | 四旋翼（未公开电机参数） | 官方规格未公开 | <249 g 起飞重量 | SOURCE-002 |
| Matrice 350 RTK | 四旋翼 | 标配 2110s；可选 2112 高原静音桨 | 最大起飞重量 9.2 kg；最大载荷 2.7 kg | SOURCE-021/022 |
| Mavic 3 Enterprise | 四旋翼 | 未在本库展开 | 最大起飞重量 1050 g | SOURCE-032 |
| Agras T50 | **共轴双旋翼（8 旋翼）** | —— | 最大起飞重量 92–103 kg | SOURCE-034 |

## 桨叶更换规则（Matrice 350 RTK，SOURCE-022）

- 桨叶有型号区分：**不可混用不同型号**；更换桨叶需更换配套螺丝，建议使用螺丝胶 **243**。
- 可使用 M300 RTK 桨叶，但**仅可同时使用同一型号，不可混合**。

## 载荷限制（SOURCE-021、SOURCE-022）

- M350 RTK 最大载荷 2.7 kg，最多 3 个负载；超载荷会降低动力余量并影响安全。
- Agras T50 最大起飞重量取决于喷头数与药箱：92 kg（2 喷头+40L）→ 103 kg（4 喷头+50L 果树套件）。

## 电机异常售后要点

- 用户报"某电机不转/动力异常"，应先确认桨叶安装正确（标记桨对标记臂），
  再逐个启动电机观察是否全转（详见无法起飞故障 / SOP）。（SOURCE-006）
- 高压载重机（T50/T50 系列）动力系统检查属**高安全风险**，专业人员方可拆检（见安全文档）。

## 来源

- SOURCE-002 / SOURCE-006 / SOURCE-021 / SOURCE-022 / SOURCE-032 / SOURCE-034