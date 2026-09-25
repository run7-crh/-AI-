---
document_id: drone_case_s006_liftoff_fail
document_type: case
product_model: mini_4_pro
component: motors
fault_type: liftoff_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-006"]
---

# 模拟案例 CASE-S006：无法起飞 / 电机不转

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 内八解锁后无法起飞，一个电机不转 |
| 已知条件 | 用户自行拆装过桨叶；正处于教学/新手模式 |
| 可能原因 | 桨叶安装错误；操控模式被改动（非默认"美国手"）；电机异常；教学挡（SOURCE-006） |
| 建议排查 | 1) 确认不在禁飞区；2) 检查桨叶安装（标记对标记臂）；3) 复位操控模式；4) 逐个启动电机确认全转；5) 退出教学挡（无法起飞故障文档） |
| 参考知识 | drone_troubleshooting_liftoff_abnormal / drone_technical_power_system |
| 人工升级条件 | 排查后电机仍不转 → 升级人工寄修（附 App 截图+开机视频） |
| 来源 | SOURCE-006 |

> 提示：桨叶装错会导致动力失衡，严禁在疑似装错时试飞。