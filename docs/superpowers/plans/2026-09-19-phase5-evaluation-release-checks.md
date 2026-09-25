# 阶段 5：评估集重建、文档收口与上线前检查

## 范围

- 仅修改 `backend/eval/dataset.json`、`backend/eval/run_eval.py`、`backend/eval/build_dataset.py`、README/项目说明和相关评估测试。
- 不修改 `data/raw`、`data/drone`、知识库正文或 `manifest.json`。
- 不部署、不提交、不创建 PR。

## 成功标准

1. 评估集覆盖售后意图、安全、高风险、跨机型、模拟案例和多轮失败场景，并保留旧字段兼容性。
2. 离线评估脚本输出新增指标；缺少真实 API/GPU/联网数据时明确为 `null` 或未执行。
3. README 说明无人机售后定位、运行方式、限制和上线前检查结果。
4. 后端、前端、构建、compileall、评估测试和 diff 检查通过。

## 实施顺序

1. 在现有评估脚本中加入元数据读取与新增指标的纯函数测试。
2. 重建基于 `data/drone` 主题的评估数据集，所有事实标签注明 `reviewed` 或 `inferred`，不填充无法可靠判断的答案。
3. 扩展 API 评估采集和聚合逻辑，保留旧指标定义。
4. 更新 README 与项目说明，记录上线检查的证据和阻断项。
5. 执行离线评估、完整回归、构建、compileall、diff 检查并停止。
