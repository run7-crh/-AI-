---
document_id: drone_troubleshooting_rtk_signal_weak
document_type: troubleshooting
product_model: matrice_350_rtk
component: rtk
fault_type: rtk_signal_abnormal
source_type: official
data_type: factual
source_id: ["SOURCE-028","SOURCE-029"]
---

# 故障：RTK 已连接但提示 RTK 信号差

## 适用范围

行业级 RTK 无人机（Matrice 350 RTK 适用）（SOURCE-028）。

## 故障现象

- App 提示"RTK 信号差"；
- 已连接 RTK（D-RTK 2 或网络 RTK）但定位精度不可用。

## 可能原因（官方）

- 使用场景有遮挡（建筑、山体）；
- D-RTK 2 移动站接收卫星数量不足；
- 网络 RTK 与 D-RTK 2 移动站**切换后未重启**。

## 排查步骤（官方）

1. 确认使用场景为**空旷无遮挡**环境；检查 **D-RTK 2 移动站下的卫星数量**是否充足，可更换场地测试。
2. 若曾连接网络 RTK，直接切换到基站后不可用时，需**重启设备**。

### 网络 RTK 信号弱的补充排查（SOURCE-029）

3. 检查网络 RTK 服务是否**已开启**。
4. 检查服务**有效期**，过期后重新购买。
5. 检查网络环境；若无网络 RTK 服务，建议改用 **RTK 移动站**或到强网络信号区域。

## 处理建议

RTK 信号差优先排查遮挡与差分源切换两大原因，其次才是硬件/服务。

## 安全注意事项

- RTK 不可用时定位退化为 GNSS 精度，作业精度不符应立即降落调整，勿强行作业。

## 人工升级条件

- 空旷环境、差分源正确且重启后仍持续 RTK 差 → 升级人工。

## 来源

- SOURCE-028 / SOURCE-029