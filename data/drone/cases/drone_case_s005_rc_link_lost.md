---
document_id: drone_case_s005_rc_link_lost
document_type: case
product_model: mini_4_pro
component: remote_controller
fault_type: rc_signal_weak
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-012","SOURCE-016"]
---

# 模拟案例 CASE-S005：飞行中遥控器失联/断连

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 飞到大楼背面后图传卡住、遥控器断连，屏幕上显示信号丢失 |
| 已知条件 | 视距被建筑物遮挡；已将"信号丢失"设置为返航（RTH） |
| 可能原因 | 机体在遮挡/干扰环境下信号衰减；天线朝向未对准（SOURCE-012） |
| 建议排查 | 1) 建议上调高度越障，图传可能恢复（SOURCE-012）；2) 确认返航设置已启用，失控会自动返航（SOURCE-016）；3) 回落后检查天线朝向、固件 |
| 参考知识 | drone_sop_video_link_troubleshoot / drone_sop_rth_config / drone_technical_transmission |
| 人工升级条件 | 回落后仍频繁断连 → 升级人工寄修遥控器 |
| 来源 | SOURCE-012 / SOURCE-016 |

> 关键：飞行中断连不要慌乱猛打杆，优先依赖已设置的失控返航。