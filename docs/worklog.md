# 工作记录

只记录大任务和阶段性结果。

不记录很小的改动。

---

## 2026-05-31

### A股日频数据底座一期

- 明确了一期目标：先做数据底座，不做因子、回测、策略和看板。
- 确定了第一版技术路线：`Python + DuckDB + Parquet + Tushare Pro`。
- 确定了第一版验证范围：只拉最近 5 个交易日，先验证链路是否跑通。
- 确定了核心结果：原始数据落地、本地数据库、`daily_panel`、数据质量检查报告。
- 明确了申万行业归属的处理要求：不能只存静态行业，要保留历史归属区间。
- 建立了文档约定：以后大任务先写计划文件，再在这里记录每天完成的阶段性工作。
### 单因子 Notebook 第一轮
- 新建了 `notebooks/01_single_factor_mvp.ipynb`，先用 mock `daily_panel` 跑通 `mom_20d` 单因子研究闭环。
- Notebook 明确了 T 日收盘后信号口径，并按约定计算 `forward_return_1d / 5d / 20d`。
- 放进了 `universe_mask`、`raw / zscore / size-neutral` 三个因子版本，以及 Rank IC、分组收益、多空收益。
- 留好了 `DATA_MODE = "mock" / "duckdb"` 切换口，后面可以从 mock 切到真实 `daily_panel`。
- 把 `matplotlib` 补到 `dev` 依赖声明，便于本地直接出图。

### 单因子研究下一步规划

- Claude Code review 了 `01_single_factor_mvp.ipynb`，确认整体流程正确（预处理管线、forward return 口径、7 步检验流程）。
- 指出了 4 个改进点（函数重复、缺少行业中性化、缺少 IC decay、回测太简化），已记录到 `codex-tasks/2026-06-01-notebook-01-issues.md`，交给 Codex 执行。
- 写了下一步计划 `docs/plans/2026-06-01-next-phase-plan.md`，包含：
  - `notebooks/02_factor_batch.ipynb` 的内容设计（批量因子 + 行业中性化 + 宽基对比 + 因子入库）
  - 因子注册表 schema（`factor_registry` / `factor_values` / `factor_eval_daily`）
  - 全样本 vs 宽基限定的定位说明
  - 后续脚本化路径（`src/factor_eval/`）
