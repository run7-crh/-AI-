---
document_id: drone_case_s004_video_blackout
document_type: case
product_model: mini_4_pro
component: transmission
fault_type: video_blackout
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-011"]
---

# 模拟案例 CASE-S004：起飞后图传黑屏

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 进入飞行界面后黑屏看不到画面，仅在小区内起飞后出现 |
| 已知条件 | 飞行器与遥控器均已开机、机臂灯亮；城市建筑密集区；SD 卡为杂牌卡 |
| 可能原因 | 信道干扰、SD 卡不兼容/损坏、天线朝向、固件不匹配（SOURCE-011） |
| 建议排查 | 1) 升级固件；2) App 选"自动选择"信道并更换环境；3) 调天线朝向；4) 取出 SD 卡重连测试；5) 更换兼容移动设备（图传排查 SOP） |
| 参考知识 | drone_sop_video_link_troubleshoot / drone_technical_transmission |
| 人工升级条件 | 完成排查仍黑屏 → 升级人工附故障截图 |
| 来源 | SOURCE-011 |

> 黑屏优先排查固件/干扰/外设，多数非主机硬件故障。