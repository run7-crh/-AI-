---
document_id: drone_case_s009_pairing_after_repair
document_type: case
product_model: mini_4_pro
component: remote_controller
fault_type: link_fail
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-013","SOURCE-015"]
---

# 模拟案例 CASE-S009：维修后无法连接需重新对频

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 随心换换新机身回来后，遥控器无法连接新机 |
| 已知条件 | 换机后未做对频；设备已开机 |
| 可能原因 | 换机后未重新对频；固件可能不匹配（SOURCE-015、SOURCE-013） |
| 建议排查 | 1) 升级 DJI Fly 至最新；2) 进入对频流程：长按机身电源键 4 秒进入（SOURCE-015）；3) 确认对频成功（"嘀嘀"两声+绿灯常亮）；4) 若固件不一致先统一固件 |
| 参考知识 | drone_sop_link_pairing / drone_troubleshooting_aircraft_disconnected |
| 人工升级条件 | 多次对频失败/指示灯异常 → 升级人工 |
| 来源 | SOURCE-015 / SOURCE-013 |

> 换机/寄修/置换后重新对频是标准动作。