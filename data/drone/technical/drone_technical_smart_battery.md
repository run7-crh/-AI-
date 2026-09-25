---
document_id: drone_technical_smart_battery
document_type: technical
product_model: all
component: battery
fault_type:
source_type: official
data_type: factual
source_id: ["SOURCE-002","SOURCE-003","SOURCE-005","SOURCE-021","SOURCE-022","SOURCE-027","SOURCE-030","SOURCE-034","SOURCE-036"]
---

# 技术：智能电池与管理

智能飞行电池内置管理芯片，负责充放电保护、电量计算、存储自放电与状态监控。
**不同机型电池规格、更换规则、存储逻辑差异很大，必须按型号处理。**

## 各机型电池规格

| 机型 | 电池型号 | 容量 | 电压 | 能量 | 来源 |
|---|---|---|---|---|---|
| Mini 4 Pro（标准） | Mini 4 Pro 智能飞行电池 | 2590 mAh | 7.32 V | 18.96 Wh | SOURCE-002 |
| Mini 4 Pro（长续航） | Mini 3 系列同款长续航电池 | 3850 mAh | 7.38 V | 28.4 Wh | SOURCE-002 |
| Matrice 350 RTK | TB65 | 5880 mAh | 44.76 V | 263.2 Wh | SOURCE-021 |
| Agras T50 | DB1560 | 30 Ah | 52.22 V | — | SOURCE-034 |

## 不同类型电池的管理差异

### Mini 4 Pro（SOURCE-002、SOURCE-005）

- 首次使用需**先充电唤醒**（出厂进入休眠以保证运输安全）。
- 电池保养提示出现时，将电池**充满后静置 48 小时**。（SOURCE-003）
- 推荐 DJI 30W USB-C 或支持 USB PD 的 30W 充电器。
- 开机状态下不支持充电。

### Matrice 350 RTK（SOURCE-022）

- **双电池热插拔**：支持热替换，多架次不间断飞行。
- 电池寿命按 **12 个月 / 400 次循环 / 高电量存储 120 天，先到为准**。
- 支持 TB60 但**不可 TB60 与 TB65 混用**。
- 长期存储触发**存储自放电**到约 50% 电量，轻微发热属正常。
- 263.2 Wh 超航空随身携行限制，**不得携带登机**。

### Agras T50（SOURCE-036）

- 电芯温度 15°C–70°C 内支持快充；C10000 充电站 9–12 分钟充满一块。
- 作业后须**擦干残留农药**、盖充电插头盖帽，防腐蚀导致短路自燃。
- 电池轻拿轻放、不得直接提电源线；避免阳光直射（密闭车厢直射可达 80°C，可能燃烧）。

## 电池异常警戒信号（SOURCE-022、SOURCE-027、SOURCE-030）

出现以下情况应立即**停止使用并更换/送修**：

- 电池明显**鼓包**、**漏液**或损坏；
- App 提示电池**单体损坏 / 过放**；
- 任何疑似短路自燃前兆。

非维修：鼓包/开裂在保修内可自助寄修，过保建议购新电池。

## 售后知识主张

不同机型的电池行为（是否需唤醒、是否热插拔、是否禁带登机）**不能互相套用**。
回答用户电池问题时，务必先用产品型号定位到对应机型的电池规范。

## 来源

- SOURCE-002 / SOURCE-003 / SOURCE-005 / SOURCE-021 / SOURCE-022 / SOURCE-027 / SOURCE-030 / SOURCE-034 / SOURCE-036