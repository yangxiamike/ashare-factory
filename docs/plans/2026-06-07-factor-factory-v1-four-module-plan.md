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

第一版定位是候选因子入库前的统一体检模块：能注册因子、构建研究样本、计算因子、评价因子、输出结果，并更新 `factor_library` 状态。它不是完整交易回测系统，也不做自动挖因子、组合优化或前端 dashboard。

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
- 计算 IC、RankIC、分层收益、Top 组收益、long-short spread、覆盖率和稳定性指标。
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

### 2. sample_builder

- 负责从 `daily_panel` 生成统一研究样本。
- 处理股票池口径、可交易 mask、停牌过滤、主板过滤、上市交易日过滤。
- 统一 forward return 对齐规则：

```text
fwd_hd = adj_close[t+h+1] / adj_close[t+1] - 1
```

- 默认输出 `fwd_1d / fwd_3d / fwd_5d / fwd_10d / fwd_20d`。
- 第一版主评估口径仍以 3-5 日短线为主，`fwd_5d` 作为 primary horizon。

### 3. factor_research

- 负责因子注册、因子计算和因子预处理。
- 因子注册表使用 YAML，作为候选因子的唯一入口。
- 第一版只支持 `builtin:*` 实现，不做公式解析器。
- 首批 demo 因子：
  - `momentum_20d_v1`
  - `reversal_5d_v1`
  - `volatility_20d_v1`
- 预处理流程固定为：

```text
raw factor -> MAD winsorize -> cross-sectional zscore -> optional neutralization
```

- 默认评价口径使用市值中性化；行业 + 市值中性化作为可选口径。

### 4. factor_evaluation

- 负责因子评价、gate 和 `factor_library` 入库状态。
- 必须输出 IC、RankIC、IC IR、胜率、覆盖率、分层收益、top/bottom、long-short spread、因子自相关。
- gate 阈值写在 `configs/evaluation.yaml`，不写死在代码里。
- gate 状态固定为：

```text
candidate / active / watch / rejected
```

- 输出：
  - `outputs/evaluation_results/{factor_id}_{run_id}.json`
  - `outputs/factor_library/factor_library.json`
  - `reports/factor_evaluation/{factor_id}_{run_id}.md`

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
      library.py                     # update_factor_library
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
    direction: str
    lookback_days: int
    data_fields: list[str]
    status: str
    description: str
    hypothesis: str
```

还需要：

- `SampleConfig`：股票池、日期范围、上市交易日过滤、forward horizons。
- `EvaluationConfig`：primary horizon、分组数、预处理口径、gate 阈值。
- `EvaluationResult`：评价指标、样本信息、gate 结果、输出路径。
- `GateDecision`：状态和原因列表。

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
- `numpy`：数值计算。
- `statsmodels`：中性化和回归检验。
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
python -m ashare_factor.cli evaluate-factor --factor-id momentum_20d_v1 --start-date 20220101 --end-date 20260531
```

第二步再补：

```powershell
python -m ashare_factor.cli evaluate-all --start-date 20220101 --end-date 20260531
python -m ashare_factor.cli show-result --factor-id momentum_20d_v1
```

CLI 只负责串联四模块，不在 CLI 里写业务计算逻辑。

## Implementation Order

1. 新增 `ashare_factor.models`，定义 `FactorSpec / SampleConfig / EvaluationConfig / EvaluationResult / GateDecision`。
2. 新增 YAML 配置：`factor_registry.yaml`、`evaluation.yaml`、`universe.yaml`。
3. 实现 `sample_builder`：读取 `daily_panel`、构建可交易样本、计算 forward returns。
4. 实现 `factor_research`：读取注册表、计算 3 个 demo 因子、完成预处理。
5. 实现 `factor_evaluation`：复用现有 IC、分层收益、自相关等逻辑，输出统一 `EvaluationResult`。
6. 实现 gate 和 `factor_library.json` 更新。
7. 实现 Markdown 报告。
8. 实现 CLI。
9. 更新或保留薄 wrapper，让旧 notebook 不被立即破坏。
10. 新增测试并跑通 `momentum_20d_v1` demo。

## Acceptance Criteria

- 可以从已有 DuckDB 读取 `daily_panel`，并检查关键字段是否存在。
- 不破坏原有数据采集、入库、`build-panel` 和 DQ 流程。
- 可以构建主板研究样本，生成可交易 mask 和 `fwd_1d / fwd_3d / fwd_5d / fwd_10d / fwd_20d`。
- 可以读取 `factor_registry.yaml`，校验 `factor_id` 唯一和必填字段。
- 至少跑通 `momentum_20d_v1 / reversal_5d_v1 / volatility_20d_v1` 三个 demo 因子。
- 因子值可以输出标准长表，至少包含 `trade_date / ts_code / factor_id / factor_value_raw`。
- 可以完成 winsorize、zscore 和可选市值中性化。
- 可以计算 IC、RankIC、IC mean、IC std、IC IR、IC win rate、分层收益、Top 组收益、long-short spread 和 coverage。
- 可以根据 `configs/evaluation.yaml` 的 gate 规则输出 `active / watch / rejected`，并给出 reasons。
- 可以生成 `evaluation_result.json`、`factor_library.json` 和 Markdown 因子评价报告。
- CLI 至少支持 `list-factors` 和 `evaluate-factor`。

## Test Plan

单元测试：

- registry 能读取 YAML。
- `factor_id` 唯一。
- `FactorSpec` 必填字段缺失时失败。
- forward return 使用 T+1 到 T+h+1 口径。
- 可交易 mask 排除停牌、关键字段缺失和上市交易日不足样本。
- zscore 后横截面均值接近 0。
- gate 能输出 `active / watch / rejected`。

集成测试：

- 用小型 DataFrame 跑通 `build_sample -> calculate_factor -> preprocess_factor -> evaluate_factor -> apply_gate`。
- CLI 能 `list-factors`。
- CLI 能跑单个 demo 因子并生成 JSON、Markdown 和 `factor_library.json`。
- 现有 `factor_eval` / notebook 入口不被破坏，或已明确迁移到新入口。

## Assumptions

- `data_prep` 本轮只作为输入，不重构。
- 因子工厂 v1 只处理 A 股日频数据。
- 首版重点是工程闭环稳定，不追求因子本身有效。
- 因子值中间结果默认不全量落盘，需要时由配置打开。
- 本阶段完成后按仓库要求单独 commit。
