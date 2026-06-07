# 因子工厂 v1 四模块实现

状态：已解决

## 任务

根据 `docs/plans/2026-06-07-factor-factory-v1-four-module-plan.md` 实现第一版 A 股日频因子工厂闭环。

## 验收口径

- 新增 `ashare_factor` 包，覆盖样本构建、因子注册、因子计算、预处理、评价、gate、factor_library 和 CLI。
- 三个 demo 因子可注册和计算：`momentum_20d_v1`、`reversal_5d_v1`、`volatility_20d_v1`。
- CLI 支持 `list-factors`、`validate-registry`、`evaluate-factor`、`evaluate-all`、`show-result`。
- 评价结果包含 `data_snapshot`、`code_version`、IS/OOS、baseline placeholder、三层 gate 和输出路径。

## Codex 最终方案

与方案主口径一致：保留现有数据底座，只新增轻量因子工厂闭环。成交额阈值按 Tushare `daily.amount` 的千元单位换算，`universe.yaml` 使用 `1000` 表示约 100 万元；报告目录若受沙箱权限限制，自动 fallback 到 `outputs/factor_evaluation`。
