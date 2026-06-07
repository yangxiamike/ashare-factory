# factor_utils 收口整合计划

## 任务名称

把 `src/factor_utils.py` 从核心研究工具模块降级为 legacy 兼容层，并把核心能力收口到 `ashare_factor`。

## 背景

当前项目已经有新版 `ashare_factor` 因子工厂，但旧版 `factor_utils.py` 仍被多处调用：

- `src/factor_eval/runner.py`
- `src/factor_eval/report.py`
- `src/ashare_factor/factor_evaluation/metrics.py`
- `src/ashare_factor/factor_research/preprocessing.py`
- `notebooks/01_single_factor_mvp.ipynb`
- `notebooks/02_single_factor_eval.ipynb`
- `scripts/build_02_notebook.py`

这会导致两个问题：

- 同一类逻辑在新旧模块之间继续分叉，例如 forward return、分层收益、IC、缩尾、中性化。
- 新版因子工厂仍依赖旧模块，后续修偏差或改口径时容易漏掉一边。

本计划的目标不是立刻删除 `factor_utils.py`，而是先把新版主流程从它身上解耦。

## 目标

- 新版 `ashare_factor` 内部不再 import `factor_utils`。
- `factor_utils.py` 只保留给旧 notebook / 旧 `factor_eval` 临时兼容。
- 核心研究口径统一沉到 `ashare_factor` 包内。
- 后续新因子、新评估、新样本构建只走 `ashare_factor`。

## 不做范围

- 本轮不重写 notebook 的展示逻辑。
- 本轮不删除 `src/factor_eval/`。
- 本轮不删除 `src/factor_utils.py`。
- 本轮不改数据仓库 schema。
- 本轮不重新补数。

## 当前职责拆分

### 应迁到 `ashare_factor.sample_builder`

- `load_daily_panel`
- forward return 计算口径
- 可交易 mask
- 股票池 / 新股过滤 / 停牌和涨跌停处理

新版已有基础：

- `src/ashare_factor/sample_builder/sample.py`
- `src/ashare_factor/sample_builder/forward_returns.py`
- `src/ashare_factor/sample_builder/universe.py`

### 应迁到 `ashare_factor.factor_research`

- `compute_momentum`
- `winsorize_mad`
- `cross_sectional_zscore`
- `neutralize_by_size`
- `neutralize_by_industry_and_size`
- `build_factor` 中的预处理核心逻辑

新版已有基础：

- `src/ashare_factor/factor_research/builtins.py`
- `src/ashare_factor/factor_research/preprocessing.py`
- `src/ashare_factor/factor_research/calculator.py`

### 应迁到 `ashare_factor.factor_evaluation`

- `assign_quantiles`
- `compute_rank_ic`
- `compute_ic_decay`
- `compute_quantile_returns`
- `long_short_spread`
- `rebalance_cumulative_returns`
- `ls_summary`
- `factor_autocorr`
- `factor_autocorr_multi_lag`
- `factor_industry_exposure`
- `monthly_ic_heatmap`
- `compute_factor_return_t`

新版已有基础：

- `src/ashare_factor/factor_evaluation/metrics.py`
- `src/ashare_factor/factor_evaluation/evaluator.py`
- `src/ashare_factor/factor_evaluation/report.py`

## 实现顺序

1. 在 `ashare_factor.factor_research.preprocessing` 内补齐本地预处理函数。

   先把 `winsorize_mad`、`cross_sectional_zscore`、`neutralize_by_size`、`neutralize_by_industry_and_size` 搬进新版模块，随后删除这里对 `factor_utils` 的 import。

2. 在 `ashare_factor.factor_evaluation.metrics` 内补齐指标函数。

   先把 `assign_quantiles`、`compute_rank_ic`、`compute_quantile_returns`、`long_short_spread`、`factor_autocorr_multi_lag`、`factor_industry_exposure` 搬进新版模块，随后删除这里对 `factor_utils` 的 import。

3. 梳理 `factor_eval/report.py` 对 `factor_utils` 的依赖。

   如果这部分仍只服务旧 notebook，先保持不动，并在模块顶部或文档里标记 legacy。不要把旧 `factor_eval` 和新版 `ashare_factor` 混在同一个重构里。

4. 更新测试。

   新版测试应直接覆盖 `ashare_factor` 的函数，不再通过 `factor_utils` 间接覆盖新版逻辑。旧 `tests/test_factor_utils.py` 可以保留，目标是保证 legacy 入口短期不坏。

5. 更新 notebook 生成脚本。

   把 `scripts/build_02_notebook.py` 从 `factor_utils.compute_momentum` 切到新版 builtin 因子计算，或者改成通过 `ashare_factor.cli evaluate-factor` 生成结果。

6. 标记旧入口。

   在 `src/factor_utils.py` 和 `src/factor_eval/` 文档层面标注 legacy，说明新研究入口是 `ashare_factor`。

7. 最后阶段再删除。

   等 notebook、脚本、旧 runner 都迁完后，再单独开一轮删除 `factor_utils.py` 和 `src/factor_eval/`。删除要作为独立 commit。

## 验收标准

- `rg "from factor_utils|import factor_utils" src/ashare_factor` 无结果。
- `pytest tests/test_ashare_factor_cli.py tests/test_sample_builder.py` 通过。
- `pytest tests/test_factor_utils.py` 仍通过，说明 legacy 入口暂时没坏。
- `python -m ashare_factor.cli validate-registry` 可运行。
- `python -m ashare_factor.cli evaluate-factor --factor-id momentum_20d_v1 --start-date 20240101 --end-date 20240131` 可运行到清晰结果或清晰数据不足提示。

## 风险和注意点

- `factor_utils.compute_forward_returns` 和新版 SQL forward return 口径不完全等价，迁移时要逐项确认 T+1 开始持仓、终点可交易、停牌不跳跃。
- `factor_utils` 里有旧 notebook 需要的展示辅助函数，不能在 notebook 迁完前删除。
- 新版 `ashare_factor` 当前仍可能受环境依赖影响，例如测试环境缺 `PyYAML` 时 CLI 测试会在 import 阶段失败；整合时顺手确认依赖声明。
- 不要为了兼容旧调用方继续在新版里保留两套同名函数。新版函数应有唯一归属，旧入口只做兼容。

## 推荐提交拆分

1. `refactor: move preprocessing helpers into ashare_factor`
2. `refactor: move evaluation metrics into ashare_factor`
3. `docs: mark factor_utils as legacy`
4. `refactor: migrate factor notebooks to ashare_factor`
5. `refactor: remove legacy factor utilities`

前两步完成后，新版主流程就能先摆脱 `factor_utils`。后面三步可以按风险单独推进。
