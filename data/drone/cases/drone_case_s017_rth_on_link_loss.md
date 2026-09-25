---
document_id: drone_case_s017_rth_on_link_loss
document_type: case
product_model: mini_4_pro
component: flight_mode
fault_type: rth_trigger
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-010","SOURCE-016"]
---

# 模拟案例 CASE-S017：图传断连后自动返航

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 飞越高楼后画面丢失，随后飞行器自己飞回并降落，用户不了解为何返航 |
| 已知条件 | 已将"信号丢失=返航"（RTH）；起飞点开阔可记录返航点 |
| 可能原因 | **失控返航**：遥控信号丢失且设置为 RTH 时自动触发（SOURCE-010、SOURCE-016） |
| 建议排查 | 1) 向用户说明此为已设置的失控返航在正常工作；2) 确认返航高度是否高于障碍物；3) 若返航路径异常，结合飞行数据评估是否需排除遮挡/干扰 |
| 参考知识 | drone_sop_rth_config / drone_technical_flight_modes / drone_safety_abnormal_flight |
| 人工升级条件 | 返航点未记录或返航路径异常、造成风险 → 升级人工 |
| 来源 | SOURCE-010 / SOURCE-016 |

> 演示 Agent 能否区分"正常触发返航"与"返航功能异常"。