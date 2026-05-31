# 股票多因子第一个研究产物计划：Notebook 版标准化单因子检测器

## 任务名

先用一个 Notebook 跑通 `mom_20d` 单因子的完整研究闭环。

## 一句话目标

第一轮全部以 `notebooks/01_single_factor_mvp.ipynb` 为主完成。

暂时不拆 `src/` 模块。

但 Notebook 不能写成散乱脚本，必须用清晰函数组织，固定后续所有因子的输出范式。

## 为什么先用 Notebook

多因子第一轮最重要的不是“工程化”，而是看清楚每一步：

- 数据长什么样。
- 因子怎么算出来。
- 有没有未来函数风险。
- 预处理前后发生了什么。
- IC 和分组收益怎么得到。
- 报告里的结论是否可信。

Notebook 更适合第一轮，因为它透明、可检查、方便调整口径。

等 `01_single_factor_mvp.ipynb` 跑通、口径稳定后，第二轮再把稳定函数抽到 `src/`。

## 参考范式

第一版不凭想象做，参考主流量化工具的成熟分工。

### Alphalens

参考它的单因子分析范式：

- 一个因子对应一个 `factor_data`。
- `factor_data` 以日期和股票为索引。
- 每个样本包含因子值、未来收益、分组信息、行业/分组信息。
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

## 当前定位

这是股票多因子系统的第一个研究产物。

它不是完整策略系统，也不是完整回测平台。

它的定位是：

```text
daily_panel
  -> Notebook 内读取数据
  -> Notebook 内计算 mom_20d
  -> Notebook 内做时间安全检查
  -> Notebook 内做因子预处理
  -> Notebook 内计算 forward return
  -> Notebook 内做单因子评价
  -> Notebook 内输出检测报告
```

后面每新增一个因子，都先复用这个 Notebook 固定下来的范式。

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
- 先确认时间线、forward return、预处理和报告口径。
- 等范式稳定后，再批量扩展其他因子。

## 时间线约定

第一轮统一采用日频收盘后研究口径。

### 基础时间线

```text
T 日收盘后：
  可以使用 T 日及以前已经可得的数据计算因子。

T+1 日：
  才允许作为最早交易或收益评价起点。

T+1 到 T+N：
  用来计算 forward return。
```

### 明确禁止

- 不允许用 T 日因子预测 T 日收益。
- 不允许用 T+1 之后的信息修正 T 日因子。
- 不允许用全样本均值、标准差、分位数处理历史截面。
- 不允许用最新行业覆盖历史行业。
- 不允许用未来成分股、未来 ST 状态、未来停牌状态筛选历史股票池。

## Point-in-time 要求

每个字段都要回答：

> 在这个交易日收盘后，当时是否已经知道？

第一轮重点检查：

- 行业归属：必须是历史行业归属。
- 市值：使用当日可得市值。
- 停牌状态：使用当日状态，不能用未来状态回填。
- 上市状态：不能只保留现在仍上市的股票。
- 复权价格：要确认复权因子是否引入未来调整信息。

如果某类字段暂时无法严格 point-in-time，Notebook 报告里必须标记风险。

## Notebook 结构要求

`01_single_factor_mvp.ipynb` 必须分成清晰章节。

建议结构：

```text
1. 研究目标和时间线说明
2. 参数配置
3. 读取 daily_panel
4. daily_panel 字段检查
5. 计算 mom_20d
6. 构造 factor_data
7. 基础覆盖率和缺失检查
8. 去极值
9. 标准化
10. 行业中性化
11. 市值中性化
12. 计算 forward return
13. 计算 Rank IC
14. 计算分组收益
15. 前后样本稳定性检查
16. 生成单因子检测报告
17. 结论和风险标记
```

## Notebook 函数组织要求

虽然第一轮不拆 `src/`，但 Notebook 里必须函数化。

建议至少包含这些函数：

```text
load_daily_panel()
validate_daily_panel_schema()
compute_mom_20d()
build_factor_data()
check_factor_coverage()
winsorize_mad()
zscore_by_date()
neutralize_by_industry()
neutralize_by_size()
compute_forward_returns()
compute_rank_ic()
compute_quantile_returns()
split_sample_summary()
render_factor_report()
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
factor_value_raw
factor_value_winsorized
factor_value_zscore
factor_value_neutralized
forward_return_1d
forward_return_5d
forward_return_20d
quantile
industry
market_cap
point_in_time_warning
```

这个表就是后续所有因子检测的标准输入。

## 这次要做什么

### 1. daily_panel 字段契约

先约定 Notebook 需要的最小字段：

- `trade_date`
- `ts_code`
- `close`
- `total_mv` 或 `circ_mv`
- `industry`
- `is_suspend`

可选字段：

- `amount`
- `turnover_rate`
- `pe`
- `pb`
- `limit_up`
- `limit_down`

如果真实字段名不同，先在 Notebook 里做一层字段映射。

### 2. mom_20d 因子计算

计算口径：

```text
mom_20d = close(T) / close(T-20) - 1
```

注意：

- 只能使用 T 日及以前价格。
- 每只股票单独按交易日排序。
- 数据不足 20 个交易日时，因子值为空。

### 3. 因子基础检查

Notebook 内输出：

- 覆盖率。
- 缺失率。
- 每日有效股票数量。
- 极端值分布。
- 行业覆盖情况。
- 市值分布情况。
- 可疑值标记。

### 4. 因子预处理

这些是单因子检测器本体的一部分。

第一轮每类先支持一种常用方法：

- 去极值：MAD 去极值。
- 标准化：每日横截面 Z-score。
- 行业中性化：每日横截面行业哑变量回归，取残差。
- 市值中性化：每日横截面 `log(market_cap)` 回归，取残差。

所有处理都只能在当日横截面内完成。

Notebook 至少对比三组结果：

- 原始因子。
- 去极值 + 标准化因子。
- 行业 + 市值中性化因子。

### 5. forward return 计算

先支持：

- 未来 1 日收益。
- 未来 5 日收益。
- 未来 20 日收益。

默认口径：

```text
T 日因子 -> T+1 到 T+N 收益
```

第一轮先推荐：

```text
T 日收盘信号 -> T+1 收盘到 T+N 收盘收益
```

如果数据库暂时没有足够历史长度，Notebook 中保留字段，指标允许为空。

### 6. 单因子评价

第一轮至少输出：

- Rank IC。
- Rank IC 均值。
- Rank IC 胜率。
- Rank IC 时间序列。
- 5 组分组收益。
- 最高组减最低组的多空收益。
- 每组股票数量。
- 因子覆盖率。
- 行业中性前后对比。
- 市值中性前后对比。

### 7. Walk-forward 意识

第一轮不训练模型，所以不做完整 walk-forward 训练。

但 Notebook 必须支持样本切分：

- 全样本。
- 前半段。
- 后半段。

明确禁止：

- 用全历史挑出表现好的因子后，直接宣称它未来有效。
- 用全样本优化参数，再用同一段样本验收。

## 第一轮不做什么

- 不拆 `src/` 模块。
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
- `Statsmodels`：行业和市值中性化回归。
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

## 验收标准

第一轮完成时，应满足：

- `notebooks/01_single_factor_mvp.ipynb` 可以从头到尾顺序运行。
- Notebook 能从 `daily_panel` 读取数据。
- Notebook 能校验 `daily_panel` 是否满足最小字段契约。
- Notebook 能生成 `mom_20d` 因子。
- Notebook 能构造标准 `factor_data`。
- Notebook 能完成覆盖率、缺失率和极端值检查。
- Notebook 能完成 MAD 去极值。
- Notebook 能完成每日横截面 Z-score 标准化。
- Notebook 能完成行业中性化。
- Notebook 能完成市值中性化。
- Notebook 能严格按 `T 日因子 -> T+1 以后收益` 计算 forward return。
- Notebook 能计算未来 1 日、5 日、20 日收益。
- Notebook 能计算 Rank IC、IC 均值和 IC 胜率。
- Notebook 能按因子值分成 5 组，并输出分组收益。
- Notebook 能输出最高组减最低组的多空收益。
- Notebook 能输出中性化前后对比。
- Notebook 能输出前后样本稳定性对比。
- Notebook 能在报告中标记 point-in-time 风险。
- Notebook 最后一节能给出可读的初步结论。

## 风险和注意点

- 数据库一期刚完成时，历史长度可能不够，未来 20 日收益可能暂时无法完整验证。
- 行业归属必须使用历史行业，不能用最新行业覆盖历史。
- 市值中性化优先使用对数市值，避免市值量级过大。
- 停牌、涨跌停、新股和 ST 会影响评价结果，第一轮先记录问题，后续再做更严格股票池过滤。
- 复权价格和复权因子要特别检查是否存在未来信息。
- Notebook 不能变成一次性手工脚本，否则第二轮无法稳定抽模块。
- 单因子检测有效，不代表组合一定赚钱。本阶段只判断因子有没有基础研究价值。

## 今天做到什么程度

今天先完成这个研究产物计划。

也就是：

- 定清楚第一轮只做 `01_single_factor_mvp.ipynb`。
- 定清楚第一轮只跑通 `mom_20d`。
- 定清楚 Notebook 必须函数化组织。
- 定清楚 `factor_data` 输出范式。
- 定清楚未来函数、point-in-time、时间错位和 walk-forward 意识要内嵌在 Notebook 里。
- 定清楚第一轮不拆 `src/`。
- 不和数据库一期开发抢同一块工作。

等 `daily_panel` 可用后，再按这个计划进入 Notebook 开发。
