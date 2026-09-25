---
document_id: drone_case_s008_firmware_stuck
document_type: case
product_model: mini_4_pro
component: firmware
fault_type: firmware_update_abnormal
source_type: synthetic
data_type: synthetic
source_id: ["SOURCE-014"]
---

# 模拟案例 CASE-S008：固件升级卡在进度条

| 字段 | 内容 |
|---|---|
| 产品型号 | DJI Mini 4 Pro |
| case_type | synthetic |
| 用户描述 | 升级固件到 40% 卡住，提示升级失败 |
| 已知条件 | 手机电量低，升级中网络偶断 |
| 可能原因 | 设备电量 <50%；升级中断/断网；固件下载异常（SOURCE-014） |
| 建议排查 | 1) 先给设备充电到 >50%；2) 重启产品与移动设备后重试；3) 网络异常改用 DJI Assistant 2（电脑端）升级；4) 保留报错截图 |
| 参考知识 | drone_troubleshooting_firmware_update_failed / drone_technical_firmware |
| 人工升级条件 | 电脑端仍失败 → 升级人工附报错截图 |
| 来源 | SOURCE-014 |

> 升级过程中勿断电/插拔，以免固件损坏。