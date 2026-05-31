# 股票多因子第一个研究产物计划：Notebook 版 `mom_20d` 单因子闭环

## 任务名

先用一个 Notebook 跑通 `mom_20d` 单因子的完整研究闭环。

## 一句话目标

第一轮全部以 `notebooks/01_single_factor_mvp.ipynb` 为主完成。

暂时不拆 `src/` 模块。

Notebook 不能写成散乱脚本，必须用清晰函数组织。目标是跑通一个透明、可检查、时间线正确的单因子研究闭环，并固定后续所有因子的 Notebook 输出范式。

## 为什么先用 Notebook

多因子第一轮最重要的不是工程化，而是看清楚每一步：

- 数据长什么样。
- 因子怎么算出来。
- 股票池怎么过滤。
- 有没有未来函数风险。
- 预处理前后发生了什么。
- forward return 标签怎么生成。
- IC 和分组收益怎么得到。
- 报告里的结论是否可信。

Notebook 更适合第一轮，因为它透明、可检查、方便调整口径。

等 `01_single_factor_mvp.ipynb` 跑通、口径稳定后，第二轮再把稳定函数抽到 `src/`。

## 当前定位

这是股票多因子系统的第一个研究产物。

它不是完整策略系统，也不是完整回测平台。

第一轮链路是：

```text
daily_panel
  -> Notebook 内读取数据
  -> 字段校验和 PIT audit
  -> 构造每日动态股票池 universe_mask
  -> 计算 mom_20d
  -> 构造 factor_data
  -> 生成 raw / zscore / size-neutral 三个因子版本
  -> 按 T 收盘后信号口径计算 forward return
  -> 计算 IC / 分组收益 / 多空收益 / 稳定性
  -> Notebook 内输出结论和风险标记
```

## 参考范式

第一版不凭想象做，参考主流量化工具的成熟分工。

### Alphalens

参考它的单因子分析范式：

- 一个因子对应一个 `factor_data`。
- `factor_data` 以日期和股票为索引。
- 每个样本包含因子值、未来收益、分组信息、行业或分组信息。
- 核心报告包括收益分析、IC 分析、分组收益、换手分析。
- 支持 long-short 和 group neutral 视角。

我们第一轮只学习它的结构，不直接接入它。

### Qlib

参考它的研究流水线分层：

- 数据加载。
- 数据处理。
- 时间切片。
- 信号生成。
- 评价。
- 回测。
- 实验结果沉淀。

我们第一轮只做其中的“因子信号生成 + 因子评价”。

### Zipline / Backtrader

参考它们对时间推进和未来函数的约束：

- 当前 bar 只能使用当前及历史信息。
- 交易执行必须和信号生成时间分开。
- 开盘成交、收盘信号、次日成交这些规则必须明确。

第一轮虽然不做完整交易回测，但必须把时间线写死。

## 第一轮只做一个因子

第一轮只做：

- `mom_20d`：过去 20 个交易日收益率。

暂时不做：

- `mom_60d`
- `vol_20d`
- `amount_20d`
- `turnover_20d`
- `size`
- `pe`
- `pb`

原因：

- 先把一个因子的完整检测链路做扎实。
- 先确认时间线、股票池、forward return、预处理和报告口径。
- 等范式稳定后，再批量扩展其他因子。

## 时间线和 forward return 口径

第一轮统一采用日频收盘后研究口径。

`mom_20d` 使用 T 日 `close` 计算，因此信号在 T 日收盘后才可得。

如果第一轮只有 `close` 数据，不使用 `close(T)` 作为买入基准，而采用收盘后信号口径：

```text
forward_return_1d  = close(T+2)  / close(T+1) - 1
forward_return_5d  = close(T+6)  / close(T+1) - 1
forward_return_20d = close(T+21) / close(T+1) - 1
```

含义是：

```text
T 日收盘后生成因子；
T+1 是最早可交易日；
用 T+1 到 T+N+1 的收益作为 forward return。
```

Notebook 中必须明确说明：

- 这是 close-to-close 的研究标签。
- 它不是严格实盘成交收益。
- 后续如果有 `open` 或 `vwap` 数据，再升级为 next-open 或 next-vwap 交易口径。

### 明确禁止

- 不允许用 T 日因子预测 T 日收益。
- 不允许把 `close(T)` 当作 T 日收盘后信号的买入价格。
- 不允许用 T+1 之后的信息修正 T 日因子。
- 不允许用全样本均值、标准差、分位数处理历史截面。
- 不允许用最新行业覆盖历史行业。
- 不允许用未来成分股、未来 ST 状态、未来停牌状态筛选历史股票池。

## 每日动态股票池 `universe_mask`

第一轮不能用当前最新股票列表回看历史。

Notebook 必须构造：

```text
universe_mask(trade_date, ts_code)
```

第一轮最小股票池规则：

- 当日有 `close`。
- 当日未停牌。
- 有足够 20 日历史价格计算 `mom_20d`。
- 有足够未来价格计算对应 forward return。
- `market_cap` 非空且大于 0。

注意：

- 未来价格只用于判断该样本是否能计算 label。
- 未来价格不允许参与因子计算。
- 股票池必须是逐日动态结果，不能用今天的股票列表回看历史。

后续再扩展：

- 剔除 ST。
- 剔除上市不足 N 日新股。
- 剔除涨跌停不可交易样本。
- 剔除创业板 / 科创板 / 北交所，如果实盘交易范围不包含它们。
- 剔除低流动性股票。

## PIT Audit

第一轮数据还没完全稳定，所以 PIT 不要求一次性解决所有问题。

但 Notebook 必须固定输出字段级 point-in-time 风险表。

建议表结构：

```text
field              PIT status        action
close              check             确认复权口径
market_cap         ok/check          使用当日市值
is_suspend         ok/check          必须是当日停牌状态
industry           risky/check       不能用最新行业覆盖历史
stock_status       risky/check       不能只保留当前仍上市股票
adj_factor         risky/check       确认复权因子是否引入未来信息
```

状态含义：

- `ok`：已确认是当时可得数据。
- `check`：字段可用，但口径需要人工确认。
- `risky`：存在明显 PIT 风险，不能直接用于正式结论。
- `missing`：字段缺失，本轮不使用或降级处理。

第一轮 PIT 做法：

- Notebook 中写死一张初始 audit 配置表。
- 根据 `daily_panel` 实际字段自动标记字段是否存在。
- 对无法确认的字段，先标记 `check` 或 `risky`。
- 最终结论必须带 PIT 风险提示。
- 行业中性化只有在 `industry` 被确认是历史 point-in-time 行业归属后，才允许进入正式评价。

## Notebook 结构要求

`01_single_factor_mvp.ipynb` 必须分成清晰章节。

建议结构：

```text
1. 研究目标、时间线和 forward return 口径说明
2. 参数配置
3. 读取 daily_panel
4. daily_panel 字段检查
5. PIT audit
6. 构造 universe_mask
7. 计算 mom_20d
8. 构造 factor_data
9. 覆盖率、缺失率和极端值检查
10. 生成 factor_value_raw
11. 生成 factor_value_zscore
12. 生成 factor_value_size_neutral
13. 计算 1d / 5d / 20d forward return
14. 计算 Rank IC、IC 均值、IC 胜率、ICIR
15. 计算 5 组分组收益
16. 计算最高组 - 最低组多空收益
17. 前半段 / 后半段稳定性检查
18. raw / zscore / size-neutral 三版本对比
19. 结论和风险标记
```

## Notebook 函数组织要求

虽然第一轮不拆 `src/`，但 Notebook 里必须函数化。

建议至少包含这些函数：

```text
load_daily_panel()
validate_daily_panel_schema()
build_pit_audit_table()
build_universe_mask()
compute_mom_20d()
build_factor_data()
check_factor_coverage()
winsorize_mad()
zscore_by_date()
neutralize_by_size()
compute_forward_returns_close_to_close()
compute_rank_ic()
compute_ic_summary()
compute_quantile_returns()
compute_long_short_returns()
split_sample_summary()
render_notebook_summary()
```

行业中性化作为可选函数：

```text
neutralize_by_industry()
neutralize_by_industry_and_size()
```

要求：

- 每个函数只做一件事。
- 每个函数输入输出清楚。
- 函数之间通过 DataFrame 传递，不依赖隐式全局变量。
- 关键函数后面要展示一小段结果，方便人工检查。

## factor_data 输出范式

第一轮最重要的固定产物是 `factor_data`。

建议字段：

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

说明：

- `factor_value_raw` = 原始 `mom_20d`。
- `factor_value_zscore` = raw -> 每日横截面 MAD 去极值 -> 每日横截面 zscore。
- `factor_value_size_neutral` = `factor_value_zscore` -> 每日横截面对 `log(market_cap)` 回归 -> 取 residual -> 可选再次 zscore。

报告主看 `factor_value_size_neutral`。

同时展示 raw / zscore / size-neutral 三个版本的 IC、分组收益和多空收益对比。

## 这次要做什么

### 1. daily_panel 字段契约

Notebook 需要的最小字段：

- `trade_date`
- `ts_code`
- `close`
- `total_mv` 或 `circ_mv`
- `is_suspend`

可选字段：

- `industry`
- `amount`
- `turnover_rate`
- `pe`
- `pb`
- `limit_up`
- `limit_down`
- `adj_factor`
- `stock_status`

如果真实字段名不同，先在 Notebook 里做一层字段映射。

### 2. `mom_20d` 因子计算

计算口径：

```text
mom_20d = close(T) / close(T-20) - 1
```

注意：

- 只能使用 T 日及以前价格。
- 每只股票单独按交易日排序。
- 数据不足 20 个交易日时，因子值为空。

### 3. 因子预处理

第一轮必须输出三个因子版本：

```text
factor_value_raw
factor_value_zscore
factor_value_size_neutral
```

处理链路：

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

第一轮不强制行业中性化。

行业中性化只有在确认 `industry` 是历史 point-in-time 行业归属后，才允许加入正式评价。

### 4. 单因子评价

第一轮至少输出：

- Rank IC。
- IC 均值。
- IC 胜率。
- ICIR。
- Rank IC 时间序列。
- 5 组分组收益。
- 最高组减最低组的多空收益。
- 每组股票数量。
- 因子覆盖率。
- raw / zscore / size-neutral 三版本对比。
- 前半段 / 后半段稳定性。

## 第一轮不做什么

- 不拆 `src/` 模块。
- 不写批量因子检测脚本。
- 不强制行业中性化。
- 不强制行业 + 市值联合中性化。
- 不强制自动 Markdown 报告。
- 不强制 PNG / CSV 批量导出。
- 不做完整多因子合成模型。
- 不做复杂组合优化。
- 不做正式交易回测系统。
- 不做交易成本、滑点和实盘成交模拟。
- 不做机器学习模型。
- 不做 dashboard。
- 不一次性接入 Qlib、Alphalens、RQAlpha 等大型框架。
- 不做几十上百个因子。

## 第一轮可选完成

- 行业中性化。
- 行业 + 市值联合中性化。
- 自动 Markdown 报告。
- PNG / CSV 批量导出。
- `src` 模块抽取。

## 技术栈

第一轮技术栈：

```text
Python
DuckDB
Pandas
NumPy
SciPy
Statsmodels
Matplotlib
Jupyter Notebook
```

分工：

- `DuckDB`：读取本地数据库和 `daily_panel`。
- `Pandas`：表格计算和横截面处理。
- `NumPy`：数值计算。
- `SciPy`：统计指标。
- `Statsmodels`：市值中性化回归。
- `Matplotlib`：基础图表。
- `Jupyter Notebook`：承载第一轮完整研究流程。

大框架策略：

- Qlib：参考系统分层。
- Alphalens：参考单因子 tear sheet。
- jqfactor_analyzer：参考 A 股单因子报告口径。
- RQAlpha：后续参考回测。

第一轮自己实现最小可控流程，避免被大框架的数据格式反向牵着走。

## 第一轮主要产物

- `notebooks/01_single_factor_mvp.ipynb`：唯一核心产物。
- Notebook 内固定的 `factor_data` 输出范式。
- Notebook 内生成的 PIT audit 表。
- Notebook 内生成的 `universe_mask`。
- Notebook 内生成的单因子检测结果表。
- Notebook 内生成的基础图表。
- Notebook 最后一节的研究结论和风险标记。

第一轮不要求新增：

- `src/factors/`
- `src/factor_eval/`
- 批量运行 CLI
- dashboard

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

## 第一轮必须完成

第一轮完成时，应满足：

- 从 `daily_panel` 读取数据。
- 校验字段。
- 输出 PIT audit。
- 构造 `universe_mask`。
- 计算 `mom_20d`。
- 构造 `factor_data`。
- 输出 raw / zscore / size-neutral 三个因子版本。
- 按 T 收盘后信号口径计算 1d / 5d / 20d forward return。
- 计算 Rank IC、IC 均值、IC 胜率、ICIR。
- 计算 5 组分组收益。
- 计算最高组 - 最低组多空收益。
- 输出前半段 / 后半段稳定性。
- Notebook 从头到尾可顺序运行。

## 第一轮可选验收

- 行业中性化。
- 行业 + 市值联合中性化。
- 自动 Markdown 报告。
- PNG / CSV 批量导出。
- `src` 模块抽取。

## 风险和注意点

- 数据库一期刚完成时，历史长度可能不够，未来 20 日收益可能暂时无法完整验证。
- 行业归属必须使用历史行业，不能用最新行业覆盖历史。
- 如果 `industry` 没有通过 PIT audit，第一轮不能把行业中性化结果作为正式评价依据。
- 市值中性化优先使用对数市值，避免市值量级过大。
- 停牌、涨跌停、新股和 ST 会影响评价结果，第一轮先记录问题，后续再做更严格股票池过滤。
- 复权价格和复权因子要特别检查是否存在未来信息。
- close-to-close forward return 是研究标签，不是严格实盘成交收益。
- Notebook 不能变成一次性手工脚本，否则第二轮无法稳定抽模块。
- 单因子检测有效，不代表组合一定赚钱。本阶段只判断因子有没有基础研究价值。

## 今天做到什么程度

今天先完成这个研究产物计划。

也就是：

- 定清楚第一轮只做 `01_single_factor_mvp.ipynb`。
- 定清楚第一轮只跑通 `mom_20d`。
- 定清楚 forward return 使用 `close(T+N+1) / close(T+1) - 1`。
- 定清楚 Notebook 必须构造 `universe_mask`。
- 定清楚第一轮必做 raw / zscore / size-neutral 三个版本。
- 定清楚行业中性化只作为可选项。
- 定清楚 PIT audit 是 Notebook 固定章节。
- 定清楚第一轮不拆 `src/`。
- 不和数据库一期开发抢同一块工作。

等 `daily_panel` 可用后，再按这个计划进入 Notebook 开发。
