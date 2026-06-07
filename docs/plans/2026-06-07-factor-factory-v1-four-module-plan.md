# 因子工厂 v1 四模块工程方案

## 本轮任务目的

本轮任务是在已经完成的数据底座上，建设第一版 A 股日频因子工厂。项目已有 DuckDB / Parquet 本地数据仓库，也已经完成基础股票数据、复权数据、停复牌、涨跌停、行业分类、指数成分和 `daily_panel` 等准备工作。

本阶段不重做数据底座，而是把已有研究原型沉淀成候选因子入库前的统一体检系统：

```text
候选因子注册 -> 候选因子计算 -> 候选因子评价 -> gate 判断 -> factor_library 状态
```

第一版只解决“候选因子能否被稳定、统一、可追踪地评价”这个问题。它不是完整交易回测系统，不是自动挖因子系统，不是组合优化系统，也不做前端 dashboard。

## Summary

目标是在现有 A 股日频数据底座上，新增一条轻量因子工厂流水线：

```text
data_prep -> sample_builder -> factor_research -> factor_evaluation
```

四个高层模块是业务工作流边界，不再额外发明新的多层架构。`sample / factors / evaluation / library` 等目录只作为内部实现拆分，不代表新的架构层级。

第一版定位是候选因子入库前的统一体检模块：能注册因子、构建研究样本、计算因子、评价因子、输出结果，并更新 `factor_library` 状态。

## 本轮最小闭环

输入：

- 已存在的 DuckDB 数据库。
- 已构建好的 `daily_panel`。
- 因子注册表 `configs/factor_registry.yaml`。
- 研究样本配置 `configs/universe.yaml`。
- 评价和 gate 配置 `configs/evaluation.yaml`。

处理：

- 从 `daily_panel` 读取日频股票数据。
- 构建统一研究样本，包括股票池、可交易 mask、forward returns 和时间对齐规则。
- 根据注册表计算 3 个 demo 因子。
- 对因子值做去极值、标准化和可选中性化。
- 计算 IC、RankIC、分层收益、交易表现、覆盖率、稳定性和分层画像指标。
- 根据 gate 规则给出 `active / watch / rejected` 状态。

输出：

- 标准化评价结果 `evaluation_result.json`。
- Markdown 因子评价报告。
- 因子库状态文件 `factor_library.json`。
- 可复用的因子注册、计算、评价工程模块。
- 可通过 CLI 运行的单因子评价流程。

## Four Modules

### 1. data_prep

- 对应现有 `src/ashare_data/`。
- 本阶段不重构数据采集、入库、`daily_panel` 构建和 DQ 流程。
- 因子工厂只读 DuckDB 里的 `daily_panel`，并检查必要字段是否存在。
- 字段、表名、路径等基础常量继续由数据底座统一维护，避免维护两套 schema。
- `evaluation_result.json` 需要记录本次使用的数据快照：`daily_panel` 的最小/最大 `trade_date`、行数、DuckDB 文件路径。

### 2. sample_builder

- 负责从 `daily_panel` 生成统一研究样本。
- 处理股票池口径、可交易 mask、停牌过滤、主板过滤和上市交易日过滤。
- 可交易 mask 必须补齐以下过滤条件：
  - 停牌样本不可交易。
  - 非主板样本按配置排除。
  - 上市交易日不足 `min_listing_days` 的样本排除。
  - 涨停日不能买入多头端，跌停日不能卖出空头端；复用现有 `factor_utils.py` 中类似 `next_open_is_limit_up` 的可成交判断。
  - ST / *ST 股票从 `stock_basic` 或 `name` 字段识别并排除。
  - 日成交额低于 `universe.yaml` 中 `min_amount` 阈值的样本标记为不可交易，默认建议 100 万元。
  - 新股前 N 个交易日可配置为额外过滤项，默认建议 20 个交易日，用于隔离炒新导致的异常样本。
- 统一 forward return 对齐规则：

```text
fwd_hd = adj_close[t+h+1] / adj_close[t+1] - 1
```

- 该公式隐含 `t+1` 和 `t+h+1` 都可以成交。若 `t+1` 停牌，样本虽然有连续复权价，也不能静默计算 forward return，必须标记为 `NaN`。若 `t+h+1` 停牌，同样标记为 `NaN`，避免收益被前值填充拉向 0。
- 默认输出 `fwd_1d / fwd_3d / fwd_5d / fwd_10d / fwd_20d`。
- 第一版主评估口径仍以 3-5 日短线为主，`fwd_5d` 作为 primary horizon。
- 某交易日截面股票数小于 30 时跳过该日，并在结果中记录 `skipped_dates`。

### 3. factor_research

- 负责因子注册、因子计算和因子预处理。
- 因子注册表使用 YAML，作为候选因子的静态定义入口。
- `factor_registry.yaml` 中的 `status` 永远等于 `candidate`。真实状态由 `factor_library.json` 维护，避免人工注册表和机器评价状态互相覆盖。
- 第一版只支持 `builtin:*` 实现，不做公式解析器。
- 首批 demo 因子：
  - `momentum_20d_v1`
  - `reversal_5d_v1`
  - `volatility_20d_v1`
- `FactorSpec.direction` 必须明确语义：
  - `positive`：因子值越大，预期未来收益越高。
  - `negative`：因子值越大，预期未来收益越低。
- 评价系统统一把 direction 调整到“期望 IC 为正”的口径后再做 gate。也就是说，负向因子要么在计算阶段输出反向值，要么在评价阶段把 IC 符号调整为方向一致口径，但只能选择一种方式并写清楚。
- `reversal_5d_v1` 推荐实现为 `factor_value = -short_term_return`，并保持 `direction = "negative"` 的业务说明。评价报告需注明实际 gate 使用的是方向调整后的 IC。
- 预处理参数统一由 `configs/evaluation.yaml` 管理，默认流程为：

```text
raw factor -> MAD winsorize -> cross-sectional zscore -> neutralize -> re-standardize
```

- neutralization 发生在 zscore 之后。这个顺序不影响 RankIC 的秩相关解释，但会影响回归 beta 和 factor exposure 的数值解释，报告中要注明。
- preprocessing 前发现因子全为 `NaN`，直接 `rejected`，reason 为 `calculation yielded all NaN`。
- preprocessing 前发现因子方差为 0，直接 `rejected`，reason 为 `constant factor values`。
- 默认评价口径使用市值中性化；行业 + 市值中性化作为可选口径。

### 4. factor_evaluation

- 负责因子评价、gate 和 `factor_library` 入库状态。
- 必须输出 IC、RankIC、IC IR、胜率、覆盖率、分层收益、top/bottom、long-short spread、因子自相关。
- IC 统计必须补充：
  - `ic_t_stat = mean_ic / (std_ic / sqrt(n_days))`。
  - 正 IC 天数占比、负 IC 天数占比，以及极端负 IC 天数占比，例如 `ic < -1 * std_ic`。
  - IC 偏度和峰度，用于识别肥尾和不稳定分布。
- 稳定性分析必须补充：
  - rolling 252 交易日 mean IC。
  - `turnover_std`，与 `mean_turnover` 一起判断分组换手稳定性。
  - IC half-life 或因子自相关衰减指标。
- 交易表现指标必须补充：
  - 年化 Sharpe。
  - Calmar。
  - 年化收益。
  - 最大回撤。
  - 换手率。
  - Q5 回测净值。
  - long-short 净值。
- 交易表现默认计算口径为：5 日调仓、等权组合、单边交易成本 0.1%，并在 `evaluation.yaml` 可配置。
- 分层画像必须补充：
  - 按 `total_mv` 分大/中/小三组分别报告 IC，用来判断因子容量。
  - 中性化后按行业报告残差均值，复用现有 `factor_industry_exposure` 思路检查行业暴露是否残留。
  - 预留牛熊市分层 IC 入口，按指数 20/60 日均线区分市场状态，第一版可只保留配置和报告字段。
- 分层单调性不能只检查 Q1 到 Q5 均值是否单调，还要报告 Q5-Q1 spread 的 t 统计量，以及相邻分组差异的 t 检验。
- `evaluation_result.json` 必须记录可复现信息：
  - `data_snapshot`：date range、row count、DuckDB 路径。
  - `code_version.git_commit`：`git rev-parse HEAD`。
  - `code_version.config_hashes`：registry / universe / evaluation yaml 的 md5。
- gate 阈值写在 `configs/evaluation.yaml`，不写死在代码里。
- gate 状态固定为：

```text
active / watch / rejected
```

- `candidate` 是注册表初始状态，不是评价后的最终状态。
- `archived` 是 `factor_library.json` 的运营状态，用于标记曾经有效但后来失效的因子。
- 输出：
  - `outputs/evaluation_results/{factor_id}_{run_id}.json`
  - `outputs/factor_library/factor_library.json`
  - `reports/factor_evaluation/{factor_id}_{run_id}.md`

## Gate 设计

gate 分为 hard gate 和 soft gate。

Hard gate 是准入条件，任一失败直接 `rejected`：

- `mean_rank_ic > 0`：方向调整后仍必须为正。
- `coverage_pct > 0.3`：覆盖率过低时样本偏差不可接受。
- `n_valid_dates > 60`：有效交易日过少时统计不可靠。

Soft gate 是加权评分：

- 每个指标映射到 0-10 分。
- 阈值之间用线性插值补全。
- `score >= 6.5` 为 `active`。
- `4.0 <= score < 6.5` 为 `watch`。
- `score < 4.0` 为 `rejected`。
- momentum / reversal / volatility 支持 category override 调整权重。
- `GateDecision.reasons` 需要记录 hard fail 原因、低分指标、每个指标得分和总分。

Gate YAML 草案已落在 `configs/evaluation.yaml`。核心结构如下：

```yaml
gate:
  hard:
    - metric: mean_rank_ic
      operator: ">"
      threshold: 0.0
      reason_on_fail: "IC方向错误或零预测能力"
    - metric: coverage_pct
      operator: ">"
      threshold: 0.3
      reason_on_fail: "因子覆盖率不足，样本偏差严重"
    - metric: n_valid_dates
      operator: ">"
      threshold: 60
      reason_on_fail: "有效交易日过少，统计不可靠"

  soft:
    decision:
      active: "score >= 6.5"
      watch: "score >= 4.0"
```

## factor_library 状态管理

- `factor_registry.yaml` 是静态定义，走 git，人工维护。
- `factor_registry.yaml.status` 固定为 `candidate`。
- `factor_library.json` 是状态唯一权威来源，机器生成，每次 evaluate 后更新。
- `factor_library.json` 支持状态：`candidate / active / watch / rejected / archived`。
- `factor_library.json` 至少保存最近一次评价摘要：
  - `status`
  - `last_run_id`
  - `last_evaluated_at`
  - `mean_rank_ic`
  - `ic_ir`
  - `long_short_sharpe`
  - `max_drawdown`
  - `mean_turnover`
  - `turnover_std`
  - `coverage_pct`
  - `reasons`

## 因子值数据契约

- 内部计算使用宽表：`trade_date / ts_code` 为索引，每个因子一列，便于 pandas 向量化。
- 入库和持久化使用长表：`trade_date / ts_code / factor_id / factor_value_raw / factor_value_processed`。
- 长表使用 `factor_id + trade_date + ts_code` 作为查询和去重主键口径，便于 DuckDB 查询。
- `factor_library.py` 负责宽表与长表之间的 pivot / unpivot 转换。
- 评价流程默认不全量保存中间因子值，需要时通过配置打开。

## Code Structure

建议新增因子工厂包，保留现有数据底座：

```text
src/
  ashare_data/                       # data_prep，已有，不动

  ashare_factor/
    __init__.py
    models.py                        # 少量 dataclass 数据契约
    cli.py                           # 因子工厂命令行入口

    sample_builder/
      __init__.py
      sample.py                      # build_sample
      forward_returns.py             # compute_forward_returns
      universe.py                    # universe / tradable mask

    factor_research/
      __init__.py
      registry.py                    # load registry / get_factor
      builtins.py                    # 内置因子函数
      calculator.py                  # calculate_factor
      preprocessing.py               # winsorize / zscore / neutralize

    factor_evaluation/
      __init__.py
      evaluator.py                   # evaluate_factor
      metrics.py                     # IC / quantile / autocorr / coverage
      gate.py                        # apply_gate
      library.py                     # update_factor_library；pivot / unpivot
      report.py                      # Markdown report
```

现有 `src/factor_utils.py` 和 `src/factor_eval/` 是已跑通的研究原型和评估引擎。实现时应复用其中稳定逻辑，但新模块稳定后要把调用入口收敛到 `ashare_factor`，避免长期维护两套主流程。旧 notebook 如需兼容，只保留薄 wrapper，不复制核心逻辑。

配置和输出目录：

```text
configs/
  factor_registry.yaml
  evaluation.yaml
  universe.yaml

outputs/
  evaluation_results/
  factor_library/
  factor_values/                     # 可选，默认不保存全部中间因子值

reports/
  factor_evaluation/
```

## Public Interfaces

函数为主，少量 dataclass 做稳定数据契约；不引入空壳式 service class。

核心函数：

```python
build_sample(...)
load_factor_registry(...)
get_factor(...)
calculate_factor(...)
preprocess_factor(...)
evaluate_factor(...)
apply_gate(...)
update_factor_library(...)
write_evaluation_report(...)
```

建议 dataclass：

```python
@dataclass(frozen=True)
class FactorSpec:
    factor_id: str
    factor_name: str
    category: str
    formula_text: str
    implementation: str
    params: dict
    direction: str  # "positive" or "negative"，表示原始业务假设方向
    lookback_days: int
    data_fields: list[str]
    status: str  # registry 中固定为 "candidate"
    description: str
    hypothesis: str
```

还需要：

- `SampleConfig`：股票池、日期范围、上市交易日过滤、forward horizons、流动性阈值、新股过滤窗口。
- `EvaluationConfig`：primary horizon、分组数、交易成本、预处理口径、gate 阈值。
- `EvaluationResult`：评价指标、样本信息、`data_snapshot`、`code_version`、gate 结果、输出路径。
- `GateDecision`：状态、原因列表、hard gate 结果、各指标分数、总分。

不建议第一版引入：

- `SampleBuilder` class
- `FactorCalculator` class
- `EvaluationService` class
- `GateEngine` class
- `LibraryManager` class

这些类当前没有必要，容易变成只有一个方法的包装壳。等后续状态、缓存、并行调度或外部服务依赖明显增加后，再考虑类。

## Tech Stack

沿用现有技术栈：

- `DuckDB`：本地数据仓库。
- `pandas`：样本构建、因子计算、横截面处理。
- `numpy`：数值计算；每天截面中性化用 `np.linalg.lstsq`，避免引入 statsmodels 完整推断开销。
- `statsmodels`：只用于需要统计推断的回归检验，例如 `compute_factor_return_t` 的 OLS t 值。
- `Typer`：CLI。
- `Jinja2`：Markdown 报告模板。
- `pytest`：单元测试和集成测试。

小幅新增：

- `PyYAML`：读取 `factor_registry.yaml`、`evaluation.yaml`、`universe.yaml`。

第一版不引入：

- Qlib / Zipline / Backtrader。
- Polars / Dask / Spark。
- 复杂公式解析器。
- 数据库 ORM。
- 前端 dashboard。

## CLI

第一版必须实现：

```powershell
python -m ashare_factor.cli list-factors
python -m ashare_factor.cli validate-registry
python -m ashare_factor.cli evaluate-factor --factor-id momentum_20d_v1 --start-date 20220101 --end-date 20260531
```

`validate-registry` 至少校验：

- `factor_id` 唯一。
- 必填字段完整。
- 引用的 `data_fields` 存在于 `daily_panel`。
- `builtin:*` 实现存在。
- `direction` 只能是 `positive` 或 `negative`。
- `status` 只能是 `candidate`。

第二步再补：

```powershell
python -m ashare_factor.cli evaluate-all --start-date 20220101 --end-date 20260531
python -m ashare_factor.cli show-result --factor-id momentum_20d_v1
```

CLI 只负责串联四模块，不在 CLI 里写业务计算逻辑。若 `daily_panel` 无数据或缺少关键字段，CLI 要给出清晰错误，不直接抛 traceback 给用户。

## Implementation Order

1. 新增 `ashare_factor.models`，定义 `FactorSpec / SampleConfig / EvaluationConfig / EvaluationResult / GateDecision`。
2. 新增 YAML 配置：`factor_registry.yaml`、`evaluation.yaml`、`universe.yaml`。
3. 实现 `sample_builder`：读取 `daily_panel`、构建可交易样本、计算 forward returns。
4. 实现 `factor_research`：读取注册表、计算 3 个 demo 因子、完成预处理。
5. 实现 `factor_evaluation`：复用现有 IC、分层收益、自相关和交易表现逻辑，输出统一 `EvaluationResult`。
6. 实现 hard gate + soft gate 和 `factor_library.json` 更新。
7. 实现 Markdown 报告。
8. 实现 CLI。
9. 更新或保留薄 wrapper，让旧 notebook 不被立即破坏。
10. 新增测试并跑通 `momentum_20d_v1` demo。

## Acceptance Criteria

- 可以从已有 DuckDB 读取 `daily_panel`，并检查关键字段是否存在。
- 不破坏原有数据采集、入库、`build-panel` 和 DQ 流程。
- 可以构建主板研究样本，生成包含停牌、涨跌停、ST、流动性、新股和上市交易日过滤的可交易 mask。
- 可以在 `t+1` 或 `t+h+1` 不可交易时把对应 forward return 标记为 `NaN`。
- 可以读取 `factor_registry.yaml`，校验 `factor_id` 唯一、必填字段、`data_fields`、`builtin:*` 实现、`direction` 和固定 `candidate` 状态。
- 至少跑通 `momentum_20d_v1 / reversal_5d_v1 / volatility_20d_v1` 三个 demo 因子。
- 因子值内部计算使用宽表，持久化输出标准长表，至少包含 `trade_date / ts_code / factor_id / factor_value_raw / factor_value_processed`。
- 可以完成 winsorize、zscore、neutralize、re-standardize，并在报告里解释中性化顺序。
- 可以计算 IC、RankIC、IC mean、IC std、IC IR、IC t-stat、IC win rate、IC skew、IC kurtosis、极端负 IC 占比、rolling 252 日 mean IC。
- 可以计算分层收益、Top 组收益、Q5 回测净值、long-short spread、年化 Sharpe、最大回撤、换手率、`turnover_std` 和 coverage。
- 可以输出市值分组 IC、行业暴露检查结果，并预留牛熊市分层 IC 字段。
- 可以根据 `configs/evaluation.yaml` 的 hard gate + soft gate 输出 `active / watch / rejected`，并给出 metric scores、total score 和 reasons。
- 可以生成带 `data_snapshot` 和 `code_version` 的 `evaluation_result.json`、`factor_library.json` 和 Markdown 因子评价报告。
- CLI 至少支持 `list-factors`、`validate-registry` 和 `evaluate-factor`。

## Test Plan

单元测试：

- registry 能读取 YAML。
- `factor_id` 唯一。
- `FactorSpec` 必填字段缺失时失败。
- `direction` 只能是 `positive` 或 `negative`。
- `status` 在 registry 中只能是 `candidate`。
- forward return 使用 T+1 到 T+h+1 口径。
- T+1 或 T+h+1 停牌时 forward return 为 `NaN`。
- 可交易 mask 排除停牌、涨跌停、ST、流动性不足、关键字段缺失、上市交易日不足和配置启用的新股窗口样本。
- zscore 后横截面均值接近 0。
- neutralize 后会 re-standardize。
- IC t-stat、skew、kurtosis、rolling mean IC、`turnover_std` 计算正确。
- gate hard fail 时直接 rejected。
- gate soft score 能通过线性插值输出 `active / watch / rejected`。
- factor_library 状态更新不回写 registry。

集成测试：

- 用小型 DataFrame 跑通 `build_sample -> calculate_factor -> preprocess_factor -> evaluate_factor -> apply_gate`。
- CLI 能 `list-factors`。
- CLI 能 `validate-registry` 并报告清晰错误。
- CLI 能跑单个 demo 因子并生成 JSON、Markdown 和 `factor_library.json`。
- `evaluation_result.json` 包含 `data_snapshot`、`code_version`、gate scores 和输出路径。
- 现有 `factor_eval` / notebook 入口不被破坏，或已明确迁移到新入口。

## Assumptions

- `data_prep` 本轮只作为输入，不重构。
- 因子工厂 v1 只处理 A 股日频数据。
- 首版重点是工程闭环稳定，不追求因子本身有效。
- 因子值中间结果默认不全量落盘，需要时由配置打开。
- 本阶段完成后按仓库要求单独 commit。
