---
document_id: drone_case_s016_low_battery_forced_land
document_type: case
product_model: mini_4_pro
component: battery
fault_type: battery_management
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-010"]
---

# 模拟案例 CASE-S016：低电量被强制降落，用户不满

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 还有"一点电"时飞行器突然强制下降，用户质疑是故障 |
| 已知条件 | 起飞时返航/备降点规划不当；任务耗时延长 |
| 可能原因 | 这是**低电量返航**安全机制：电量仅够降落时强制下降且**不可取消**（SOURCE-010） |
| 建议排查 | 1) 向用户解释为安全功能而非故障（SOURCE-010）；2) 建议起飞前确认电量余量与返航/备降点；3) 更换满电电池或缩短任务 |
| 参考知识 | drone_technical_flight_modes / drone_sop_rth_config / drone_safety_abnormal_flight |
| 人工升级条件 | 非低电量场景却强制下降 → 升级人工 |
| 来源 | SOURCE-010 |

> "低电量强制下降"是设计的安全行为，需提前向用户说明而非判定故障。