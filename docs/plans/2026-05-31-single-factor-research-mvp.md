# 股票多因子第一个研究产物计划：轻量 Notebook 版 `mom_20d` 单因子闭环

## 任务名

先用一个轻量 Notebook 跑通 `mom_20d` 单因子的完整研究闭环。

## 一句话目标

第一轮全部以 `notebooks/01_single_factor_mvp.ipynb` 为主完成。

暂时不拆 `src/` 模块。

Notebook 不做成复杂系统，但必须把核心计算逻辑、研究范式和关键图表展示清楚。

## 第一轮重点

第一轮不是为了做完整因子平台。

重点是看懂这条主线：

```text
mock daily_panel
  -> mom_20d
  -> universe_mask
  -> forward return
  -> raw / zscore / size-neutral
  -> Rank IC
  -> 分组收益
  -> 关键图表
  -> 简单结论
```

mock data 阶段只验证流程和口径，不判断真实投资有效性。

等真实 `daily_panel` 完成后，再把输入从 mock data 切到真实数据。

## 参考范式

第一版参考主流单因子研究范式，但不直接接入大框架。

- Alphalens：参考 factor_data、forward returns、quantile、IC、分组收益。
- Qlib：参考数据、信号、评价分层。
- Zipline / Backtrader：参考时间推进和防未来函数。

## 第一轮只做一个因子

第一轮只做：

- `mom_20d`：过去 20 个交易日收益率。

暂时不做：

- 多个因子批量检测。
- 行业中性化正式评价。
- 自动 Markdown 报告。
- PNG / CSV 批量导出。
- `src` 模块抽取。

## 数据策略

第一步先用 mock data。

mock `daily_panel` 至少包含：

- `trade_date`
- `ts_code`
- `close`
- `market_cap`
- `is_suspend`
- `industry`

mock data 要故意包含少量问题：

- 停牌样本。
- `close` 缺失。
- `market_cap` 缺失或小于等于 0。
- 不足 20 日历史。
- 末尾没有足够未来收益。

这些问题用来验证 `universe_mask` 和缺失处理。

第二步等真实数据完成后，再切到真实 `daily_panel`。

Notebook 可以保留一个简单配置：

```python
DATA_MODE = "mock"  # mock / duckdb
```

## 时间线和 forward return 口径

`mom_20d` 使用 T 日 `close` 计算，因此信号在 T 日收盘后才可得。

第一轮只有 close 数据时，不使用 `close(T)` 作为买入基准，而采用收盘后信号口径：

```text
forward_return_1d  = close(T+2)  / close(T+1) - 1
forward_return_5d  = close(T+6)  / close(T+1) - 1
forward_return_20d = close(T+21) / close(T+1) - 1
```

含义：

```text
T 日收盘后生成因子；
T+1 是最早可交易日；
用 T+1 到 T+N+1 的收益作为 forward return。
```

Notebook 必须明确说明：

- 这是 close-to-close 的研究标签。
- 它不是严格实盘成交收益。
- 后续如果有 `open` 或 `vwap` 数据，再升级为 next-open 或 next-vwap 交易口径。

## universe_mask

第一轮必须构造每日动态股票池：

```text
universe_mask(trade_date, ts_code)
```

最小规则：

- 当日有 `close`。
- 当日未停牌。
- 有足够 20 日历史价格计算 `mom_20d`。
- 有足够未来价格计算对应 forward return。
- `market_cap` 非空且大于 0。

注意：

- 未来价格只用于判断该样本是否能计算 label。
- 未来价格不允许参与因子计算。
- 不能用当前最新股票列表回看历史。

## 因子版本

第一轮必须输出三个版本：

```text
factor_value_raw
factor_value_zscore
factor_value_size_neutral
```

口径：

```text
factor_value_raw
  = 原始 mom_20d

factor_value_zscore
  = raw
    -> 每日横截面 MAD 去极值
    -> 每日横截面 zscore

factor_value_size_neutral
  = factor_value_zscore
    -> 每日横截面对 log(market_cap) 回归
    -> 取 residual
    -> 可选再次 zscore
```

报告主看 `factor_value_size_neutral`。

同时展示 raw / zscore / size-neutral 三个版本的 IC、分组收益和多空收益对比。

## PIT 简表

第一轮不做复杂 PIT 审计系统，但 Notebook 必须放一张字段级风险提示表。

示例：

```text
field         status   note
close         check    需要确认复权口径
market_cap    check    需要确认是否为当日市值
is_suspend    check    需要确认是否为当日停牌状态
industry      risky    未确认历史行业前，不用于正式行业中性化
stock_status  risky    不能只保留当前仍上市股票
adj_factor    check    需要确认是否引入未来信息
```

mock data 阶段，PIT 表只用于提醒风险。

真实数据接入后，再逐项确认。

## Notebook 结构

第一轮 Notebook 保持轻量。

建议结构：

```text
1. 目标和口径说明
2. 生成或读取 mock daily_panel
3. PIT 风险简表
4. 计算 mom_20d
5. 构造 universe_mask
6. 计算 forward return
7. 构造 factor_data
8. 生成 raw / zscore / size-neutral
9. 计算 Rank IC
10. 计算 5 组收益和多空收益
11. 画关键图表
12. 简单结论和风险提示
```

## Notebook 函数组织

Notebook 里要函数化，但不要工程化过度。

建议函数：

```text
make_mock_daily_panel()
compute_mom_20d()
build_universe_mask()
compute_forward_returns()
winsorize_mad()
zscore_by_date()
neutralize_by_size()
build_factor_data()
compute_rank_ic()
compute_quantile_returns()
plot_factor_diagnostics()
```

要求：

- 每个函数只做一件事。
- 函数之间通过 DataFrame 传递。
- 关键步骤后面展示一小段结果。

## 必要图表

Notebook 不能堆复杂图，但该有的图表要有。

第一轮至少画：

- `mom_20d` 原始分布图：看极端值和分布形状。
- `factor_value_size_neutral` 分布图：看预处理后的形态。
- Rank IC 时间序列图：看因子表现是否稳定。
- Rank IC 累计图：看长期方向是否持续。
- 5 组平均 forward return 柱状图：看是否有单调性。
- 多空收益时间序列或累计图：看最高组减最低组是否稳定。

可选图表：

- 每日有效样本数量图。
- raw / zscore / size-neutral 三版本 IC 对比柱状图。
- 前半段 / 后半段 IC 对比图。

## factor_data 输出范式

第一轮固定 `factor_data` 字段：

```text
trade_date
ts_code
factor_name
universe_mask
factor_value_raw
factor_value_zscore
factor_value_size_neutral
forward_return_1d
forward_return_5d
forward_return_20d
quantile_raw
quantile_zscore
quantile_size_neutral
market_cap
industry
pit_warning
```

## 第一轮必须完成

- 使用 mock `daily_panel` 跑通 Notebook。
- 构造 `universe_mask`。
- 计算 `mom_20d`。
- 构造 `factor_data`。
- 输出 raw / zscore / size-neutral 三个因子版本。
- 按 T 收盘后信号口径计算 1d / 5d / 20d forward return。
- 计算 Rank IC、IC 均值、IC 胜率、ICIR。
- 计算 5 组分组收益。
- 计算最高组 - 最低组多空收益。
- 输出前半段 / 后半段稳定性。
- 输出 PIT 风险简表。
- 画必要图表。
- Notebook 从头到尾可顺序运行。

## 第一轮可选完成

- 真实 `daily_panel` 接入。
- 行业中性化。
- 行业 + 市值联合中性化。
- 自动 Markdown 报告。
- PNG / CSV 批量导出。
- `src` 模块抽取。

## 第一轮不做什么

- 不拆 `src`。
- 不写批量因子检测脚本。
- 不做完整多因子合成模型。
- 不做复杂组合优化。
- 不做正式交易回测系统。
- 不做交易成本、滑点和实盘成交模拟。
- 不做机器学习模型。
- 不做 dashboard。
- 不一次性接入 Qlib、Alphalens、RQAlpha 等大型框架。
- 不做几十上百个因子。

## 技术栈

第一轮技术栈：

```text
Python
Pandas
NumPy
SciPy
Statsmodels
Matplotlib
Jupyter Notebook
```

真实数据接入时再使用：

```text
DuckDB
```

## 第二轮再做什么

等 Notebook 跑通后，第二轮再抽取稳定函数：

```text
src/
  factors/
  factor_eval/
```

第二轮目标：

- 把 Notebook 里的稳定函数迁移到 `src/`。
- 保留 Notebook 作为演示和人工检查入口。
- 支持更多因子复用同一套检测流程。
- 支持批量跑多个因子。
- 在有 `open` 或 `vwap` 数据后，升级交易收益口径。

## 风险和注意点

- mock data 只能验证流程，不能证明因子有效。
- close-to-close forward return 是研究标签，不是严格实盘成交收益。
- 行业归属必须使用历史行业，未确认前不做正式行业中性化。
- 市值中性化优先使用对数市值。
- 复权价格和复权因子要特别检查是否存在未来信息。
- Notebook 不能变成一次性手工脚本，否则第二轮无法稳定抽模块。
- 单因子检测有效，不代表组合一定赚钱。本阶段只判断因子有没有基础研究价值。

## 今天做到什么程度

今天先完成这个研究产物计划。

也就是：

- 定清楚第一轮先用 mock data。
- 定清楚第一轮只做 `01_single_factor_mvp.ipynb`。
- 定清楚第一轮只跑通 `mom_20d`。
- 定清楚 Notebook 要轻量，但保留必要图表。
- 定清楚 forward return 使用 `close(T+N+1) / close(T+1) - 1`。
- 定清楚第一轮必做 `universe_mask`。
- 定清楚第一轮必做 raw / zscore / size-neutral 三个版本。
- 定清楚 PIT 先做风险简表。
- 定清楚第一轮不拆 `src`。

等真实 `daily_panel` 可用后，再从 mock data 切换到真实数据。
