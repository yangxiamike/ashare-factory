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
- 根据 gate 规则给出 `invalid / rejected / watch / active` 状态。

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
- 样本构建优先下推到 DuckDB，用 SQL 完成字段裁剪、日期过滤、股票池过滤、可交易 mask 和基础派生列，避免先全量读入 pandas 再过滤。
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
- forward return 优先用 DuckDB 窗口函数 `LEAD` 生成，再输出给后续因子计算和评价模块。
- 默认输出 `fwd_1d / fwd_3d / fwd_5d / fwd_10d / fwd_20d`。
- 第一版主评估口径仍以 3-5 日短线为主，`fwd_5d` 作为 primary horizon。
- 某交易日截面股票数小于 30 时跳过该日，并在结果中记录 `skipped_dates`。

### 3. factor_research

- 负责因子注册、因子计算和因子预处理。
- 因子计算分两类：
  - SQL / 窗口类因子优先放在 DuckDB 计算，例如动量、反转、均线、成交量变化率、滚动波动率。
  - 需要复杂 Python 逻辑的因子先通过 pandas 实现，后续批量计算压力上来后迁移到 Polars 后端。
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
- 因子计算阶段保留原始业务公式，不提前为了通过评价而翻转符号；评价阶段统一把 direction 调整到“期望 IC 为正”的口径后再做 gate。
- `reversal_5d_v1` 推荐实现为 `factor_value = short_term_return`，并保持 `direction = "negative"`。评价报告需注明实际 gate 使用的是方向调整后的 IC。
- 预处理参数统一由 `configs/evaluation.yaml` 管理，默认流程为：

```text
raw factor -> MAD winsorize -> cross-sectional zscore -> neutralize -> re-standardize
```

- neutralization 发生在 zscore 之后。这个顺序不影响 RankIC 的秩相关解释，但会影响回归 beta 和 factor exposure 的数值解释，报告中要注明。
- winsorize、zscore、rank、quantile 等横截面预处理第一版可由 pandas 实现，但接口要保留计算后端边界，避免把 pandas API 泄漏成长期公共契约。
- Polars 作为后续高速后端预留，用于批量横截面 rank / zscore / winsorize / quantile 和多因子宽表计算；v1 不把 Polars 作为必选依赖。
- preprocessing 前发现因子全为 `NaN`，直接 `invalid`，reason 为 `calculation yielded all NaN`。
- preprocessing 前发现因子方差为 0，直接 `invalid`，reason 为 `constant factor values`。
- 默认评价口径使用市值中性化；行业 + 市值中性化作为可选口径。

### 4. factor_evaluation

- 负责因子评价、gate 和 `factor_library` 入库状态。
- 聚合类评价指标优先下推 DuckDB，例如覆盖率、分层收益、top/bottom 组收益和 long-short 日度收益中间表。
- 需要逐日截面 rank/corr 的指标第一版可复用 pandas 逻辑；后续批量因子评估时迁移到 Polars，减少按日期 Python 循环。
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
- gate 的三层决策规则、baseline 列表、OOS 切分和状态规则写在 `configs/evaluation.yaml`，不写死在代码里。
- gate 状态固定为：

```text
invalid / rejected / watch / active
```

- `candidate` 是注册表初始状态，不是评价后的最终状态。
- `archived` 是 `factor_library.json` 的运营状态，用于标记曾经有效但后来失效的因子。
- 输出：
  - `outputs/evaluation_results/{factor_id}_{run_id}.json`
  - `outputs/factor_library/factor_library.json`
  - `reports/factor_evaluation/{factor_id}_{run_id}.md`

## Gate 设计

v1 gate 的定位是“候选因子研究入库 gate”，不是“实盘交易准入 gate”。

核心裁决不使用固定总分阈值，例如 `score >= 6.5`。这类阈值可以作为调试观察值，但不能作为第一版的主规则。v1 更关注候选因子是否能被统一评价、是否有基本研究信号、是否强于 baseline、是否在简单 OOS 阶段没有明显失效。

v1 只实现 3 层 gate。方向预测力、分层结构、交易表现、baseline、OOS 和稳定性都是 decision evidence，不是新的架构层级，也不要拆成一堆独立 gate 模块。

```text
Validity Gate
Research Evidence Gate
Library Decision Gate
```

### 1. Validity Gate

这一层只判断因子能不能被评价，不判断因子好不好。失败状态为 `invalid`。

检查内容：

- 因子是否成功计算。
- 因子是否全 NaN。
- 因子是否为常数。
- 所需字段是否存在。
- forward return 是否能正常对齐。
- 覆盖率是否太低。
- 有效交易日是否太少。
- forward return 有效样本是否太少。
- 是否存在明显未来函数风险。

`coverage_pct >= 0.3`、`n_valid_dates >= 60` 这类阈值只代表最低可评价条件，不是好因子标准。

### 2. Research Evidence Gate

这一层合并方向预测力、分层结构和简化交易表现，用来判断因子是否有基本研究信号。

失败状态为 `rejected`。通过但证据不足时为 `watch`。

评价阶段统一做 direction adjustment，所有方向相关指标都看调整后的口径。这里的指标只是 evidence，不是独立 gate。

方向预测力 evidence：

- direction-adjusted RankIC mean。
- RankIC IR。
- RankIC win rate。
- Q5-Q1 spread。
- Top quantile return。

分层结构 evidence：

- Q1-Q5 分层收益。
- Q5-Q1 spread。
- Top quantile return。
- Top quantile win rate。

简化交易表现 evidence：

- Top quantile long-only 等权组合，这是主口径。
- Q5-Q1 long-short spread，这是研究参考口径。
- Top 组 Sharpe。
- Top 组最大回撤。
- Top 组换手率。
- 交易成本后收益。

v1 不硬性要求 `RankIC > 0.03` 或 `RankIC > 0.05` 这类绝对阈值，也不强制严格单调，不要求 `Q1 < Q2 < Q3 < Q4 < Q5`。第一版重点看方向是否正确、Top 组是否有效、Q5-Q1 spread 是否为正、分层结构是否明显反向，以及收益是否全靠极高换手和不可实现交易。

### 3. Library Decision Gate

这一层合并 baseline comparison、simple OOS 和稳定性检查，用来做最终 `rejected / watch / active` 决策。

`watch` 是 v1 的主要通过状态。`active` 必须保守。

baseline comparison evidence：

候选因子要和 baseline factor 做相对比较，而不是只看孤立指标。baseline 分三类：

1. Noise baseline：`random_normal`、`random_uniform`、`random_by_date_shuffle`。如果候选因子连随机因子都打不过，不应该进入 `active`。
2. Simple technical baseline：最朴素的 A 股短线价量因子，例如 `reversal_1d`、`reversal_3d`、`reversal_5d`、`momentum_20d`、`momentum_60d`、`volatility_20d`、`turnover_5d`、`turnover_20d`、`volume_ratio_5_20`、`amount_ratio_5_20`、`amplitude_20d`、`illiquidity_20d`。
3. Alpha101 easy subset：v1 只预留，不实现。Alpha101 全集不作为 v1 主任务，可作为后续高级 benchmark。

评价结果应报告候选因子在 baseline 分布中的位置，例如 RankIC、Top 组收益、Sharpe、最大回撤、换手率和 OOS 表现的相对分位数。这些分位数是决策证据，不是单独 gate。

simple OOS evidence：

默认方式：

```text
按 trade_date 做时间切分：
前 75% 作为 in-sample / calibration
后 25% 作为 OOS / holdout
```

OOS 只用于复核，不用于调参数、不用于选择方向、不用于优化 gate。

评价结果需要同时报告 full sample、in-sample 和 OOS。

稳定性 evidence：

- rolling 252 日 mean IC 是否长期为负。
- 分阶段表现是否集中在某一年。
- 换手和回撤是否失控。
- 市值分组和行业暴露是否显示明显不可复用的问题。

`active` 至少要求 in-sample 方向正确、OOS 方向没有反转、OOS Q5-Q1 spread 没有明显反向、OOS Top 组收益没有明显失效、强于大部分 noise baseline、相对 simple technical baseline 不差。若 IS 表现不错但 OOS 明显反向，最多给 `watch`，严重时给 `rejected`。

### 最终决策

`invalid`：

- 因子无法有效评价，例如全 NaN、常数因子、缺字段、样本太少、覆盖率太低、forward return 无法对齐。

`rejected`：

- 因子可以评价，但方向调整后 RankIC 仍然非正、Q5-Q1 spread 非正、Top 组收益明显为负、弱于大部分 noise baseline，或 IS 和 OOS 都没有预测力。

`watch`：

- v1 最常见的通过状态。因子有基本研究信号，且未被 baseline、OOS 或稳定性证据否定，但证据不足以给 `active`。

`active`：

- 必须保守。因子需通过可评价性检查，IS/OOS 方向正确，IS/OOS Q5-Q1 spread 为正，Top 组收益为正，强于大部分 noise baseline，相对 simple technical baseline 不差，分阶段表现没有明显集中在某一年，换手和回撤没有明显失控。

`active` 不代表可以实盘，只代表研究层面通过 v1 gate，可以作为候选可用因子进入 `factor_library`。

## factor_library 状态管理

- `factor_registry.yaml` 是静态定义，走 git，人工维护。
- `factor_registry.yaml.status` 固定为 `candidate`。
- `factor_library.json` 是状态唯一权威来源，机器生成，每次 evaluate 后更新。
- `factor_library.json` 支持状态：`candidate / invalid / rejected / watch / active / archived`。
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

- 内部计算使用宽表：`trade_date / ts_code` 为索引，每个因子一列，便于 pandas / Polars / NumPy 等计算后端向量化。
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
- `EvaluationConfig`：primary horizon、分组数、交易成本、预处理口径、三层 gate 配置、baseline 列表和 OOS 切分口径。
- `EvaluationResult`：评价指标、样本信息、`data_snapshot`、`code_version`、baseline 对比、OOS 复核、gate 结果、输出路径。
- `GateDecision`：状态、原因列表、`validity / research_evidence / library_decision` 三层结论，以及各指标 evidence 摘要。

不建议第一版引入：

- `SampleBuilder` class
- `FactorCalculator` class
- `EvaluationService` class
- `GateEngine` class
- `LibraryManager` class

这些类当前没有必要，容易变成只有一个方法的包装壳。等后续状态、缓存、并行调度或外部服务依赖明显增加后，再考虑类。

## Tech Stack

技术栈按职责分层，不把 pandas 作为长期批量计算主引擎：

- `DuckDB`：本地数据仓库和批处理计算引擎。优先负责样本过滤、forward returns、SQL / 窗口类因子、聚合评价中间表和结果持久化。
- `pandas`：研究工作台和兼容层。用于 notebook 探索、小样本 debug、报告展示、可视化输入，以及 v1 中暂未下推 DuckDB 的少量横截面逻辑。
- `numpy`：矩阵和数值计算。每天截面中性化用 `np.linalg.lstsq`，避免引入 statsmodels 完整推断开销。
- `statsmodels`：只用于需要统计推断的回归检验，例如 `compute_factor_return_t` 的 OLS t 值，不作为批量中性化主路径。
- `Typer`：CLI。
- `Jinja2`：Markdown 报告模板。
- `pytest`：单元测试和集成测试。

小幅新增：

- `PyYAML`：读取 `factor_registry.yaml`、`evaluation.yaml`、`universe.yaml`。

性能预留：

- `Polars`：作为 v1.1 高速计算后端预留，不作为 v1 必选依赖。优先用于批量因子的横截面 rank / zscore / winsorize / quantile、join、rolling 和多因子宽表计算。
- 公共接口不要暴露 pandas 专属对象假设；函数边界以字段契约和 DataFrame 语义为主，后续允许接入 `backend="pandas" / "polars"`。

第一版不引入：

- Qlib / Zipline / Backtrader。
- Dask / Spark。
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
3. 实现 `sample_builder`：用 DuckDB 读取 `daily_panel`、构建可交易样本、计算 forward returns。
4. 实现 `factor_research`：读取注册表，优先用 DuckDB 计算 3 个 demo 因子，完成预处理。
5. 实现 `factor_evaluation`：聚合指标优先用 DuckDB 生成中间表，复用现有 IC、分层收益、自相关和交易表现逻辑，输出统一 `EvaluationResult`。
6. 实现三层 gate：Validity Gate、Research Evidence Gate、Library Decision Gate，并更新 `factor_library.json`。
7. 实现 Markdown 报告。
8. 实现 CLI。
9. 预留 `backend` 边界，但 v1 默认仍用 DuckDB + pandas + NumPy 跑通。
10. 更新或保留薄 wrapper，让旧 notebook 不被立即破坏。
11. 新增测试并跑通 `momentum_20d_v1` demo。

## Acceptance Criteria

- 可以从已有 DuckDB 读取 `daily_panel`，并检查关键字段是否存在。
- 不破坏原有数据采集、入库、`build-panel` 和 DQ 流程。
- 样本过滤、forward returns 和 SQL / 窗口类 demo 因子优先在 DuckDB 内完成。
- 可以构建主板研究样本，生成包含停牌、涨跌停、ST、流动性、新股和上市交易日过滤的可交易 mask。
- 可以在 `t+1` 或 `t+h+1` 不可交易时把对应 forward return 标记为 `NaN`。
- 可以读取 `factor_registry.yaml`，校验 `factor_id` 唯一、必填字段、`data_fields`、`builtin:*` 实现、`direction` 和固定 `candidate` 状态。
- 至少跑通 `momentum_20d_v1 / reversal_5d_v1 / volatility_20d_v1` 三个 demo 因子。
- 因子值内部计算使用宽表，持久化输出标准长表，至少包含 `trade_date / ts_code / factor_id / factor_value_raw / factor_value_processed`。
- pandas 只作为 v1 研究兼容层和部分横截面逻辑实现，不作为公共接口的唯一计算后端假设。
- 可以完成 winsorize、zscore、neutralize、re-standardize，并在报告里解释中性化顺序。
- 可以计算 IC、RankIC、IC mean、IC std、IC IR、IC t-stat、IC win rate、IC skew、IC kurtosis、极端负 IC 占比、rolling 252 日 mean IC。
- 可以计算分层收益、Top 组收益、Q5 回测净值、long-short spread、年化 Sharpe、最大回撤、换手率、`turnover_std` 和 coverage。
- 可以输出市值分组 IC、行业暴露检查结果，并预留牛熊市分层 IC 字段。
- 可以根据 `configs/evaluation.yaml` 的三层 gate 规则输出 `invalid / rejected / watch / active`，并给出 validity、research evidence、library decision 结论和 reasons。
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
- 可评价性检查失败时直接 `invalid`。
- Research Evidence Gate 明显失败时输出 `rejected`。
- Research Evidence Gate 通过但 Library Decision Gate 证据不足时输出 `watch`。
- 只有 baseline、OOS 和稳定性证据都较稳健时才输出 `active`。
- factor_library 状态更新不回写 registry。

集成测试：

- 用小型 DataFrame 跑通 `build_sample -> calculate_factor -> preprocess_factor -> evaluate_factor -> apply_gate`。
- CLI 能 `list-factors`。
- CLI 能 `validate-registry` 并报告清晰错误。
- CLI 能跑单个 demo 因子并生成 JSON、Markdown 和 `factor_library.json`。
- `evaluation_result.json` 包含 `data_snapshot`、`code_version`、decision evidence、三层 gate 结论和输出路径。
- 现有 `factor_eval` / notebook 入口不被破坏，或已明确迁移到新入口。

## Assumptions

- `data_prep` 本轮只作为输入，不重构。
- 因子工厂 v1 只处理 A 股日频数据。
- 首版重点是工程闭环稳定，不追求因子本身有效。
- 因子值中间结果默认不全量落盘，需要时由配置打开。
- 本阶段完成后按仓库要求单独 commit。
