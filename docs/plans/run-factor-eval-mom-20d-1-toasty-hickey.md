# Codex 开发任务：单因子快速评估引擎 + 02 notebook

> **写给 Codex：** 这份文档是完整的开发规格。每个函数的输入输出、计算口径、容易踩的坑、参考谁的作图风格都写清楚了。不确定的地方优先按文档来，需要做判断的已经有说明。改完后在 TASK_BOARD.md 记录最终方案。

---

## 任务范围总览

### 要新建的文件
| 文件 | 说明 |
|---|---|
| `src/factor_eval/__init__.py` | 空，标记为 Python 包 |
| `src/factor_eval/runner.py` | 核心引擎：`run_factor_eval()` |
| `src/factor_eval/report.py` | 标准化图表：6 个 plot 函数 + 1 个 scorecard 函数 |
| `notebooks/02_single_factor_eval.ipynb` | 调用入口，演示单因子跨市场评估 |

### 不要动
- `src/factor_utils.py` — 已有的函数直接用，不要改
- `notebooks/01_single_factor_mvp.ipynb` — 完全不碰

### 不要做
- 批量多因子
- DuckDB 入库（`factor_registry` / `factor_values` / `factor_eval_daily` 表先不建）
- 暴露过多参数（除 `universe` 外全部写死）

---

## 一、`src/factor_eval/runner.py` — 核心引擎

### 1.1 EvalResult 数据结构

用 dataclass，字段全部不可变（`frozen=True`），让结果可读不可改：

```python
from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
import numpy as np

@dataclass(frozen=True)
class EvalResult:
    # 元信息
    factor_name: str
    universe: str
    start_date: str
    neutralization: str

    # 样本量
    n_stocks: int
    n_dates: int
    n_valid_rows: int

    # 因子分布的 4 个版本统计（raw / zscore / size_neutral / industry_size_neutral）
    distribution: pd.DataFrame  # columns: version, count, mean, std, skew, p01, p99

    # IC 分析
    ic_df: pd.DataFrame          # columns: trade_date, rank_ic, n_stocks（主评估期的日频 IC）
    ic_summary: dict             # {mean_ic, std_ic, ic_ir, win_rate, n_days}
    ic_decay_df: pd.DataFrame    # columns: horizon, mean_ic, std_ic, ic_ir（1~20 日衰减）
    half_life: int | None        # IC 半衰期（天数），未衰减到一半则为 None

    # 分层收益
    quantile_summary: pd.DataFrame   # columns: quantile, mean_return, std_return, hit_rate
    quantile_returns_daily: pd.DataFrame  # columns: trade_date, quantile, avg_return

    # 多空收益
    long_short_df: pd.DataFrame   # columns: trade_date, spread, cum_spread
    long_short_summary: dict      # {mean_spread, volatility, win_rate, cum_return, max_drawdown}
    is_monotonic: bool | None     # Q1→Q5 是否严格单调递增，None 表示无法判断

    # 换手率
    turnover_summary: pd.DataFrame  # columns: quantile, avg_turnover（每个分组的平均换手率）
    mean_turnover: float            # 各分组平均换手率的均值

    # 逐年绩效（仅多头 Q5）
    yearly_perf: pd.DataFrame   # columns: year, n_days, mean_ic, mean_return_q5, cum_return_q5, win_rate

    # 评分卡（一行结论）
    scorecard: pd.DataFrame     # columns: metric, value, judgement

    # 原始因子数据引用（供 report.py 画图用）
    factor_col: str             # 主因子列名，如 "factor_industry_size_neutral"
    # 完整数据框（供 report.py 按需切片）
    df: pd.DataFrame            # 加了 universe / factor_col / quantile 的完整数据
```

### 1.2 `run_factor_eval()` 主函数

```python
def run_factor_eval(
    factor_name: str,
    factor_func: callable,
    factor_kwargs: dict,
    duckdb_path: Path,
    *,
    universe: str = "全市场",
    start_date: str = "20240101",
) -> EvalResult:
```

**参数说明：**
- `factor_func`：`factor_utils` 里的因子构造函数，如 `compute_momentum`
- `factor_kwargs`：传给 factor_func 的 kwargs，如 `{"window": 20, "col_name": "mom_20d"}`
- `universe`：`"全市场"` / `"hs300"` / `"csi500"` / `"csi1000"`
- 其他参数全部写死：`neutralization="industry_size"`，`forward_horizons=(1,5,20)`，`n_quantiles=5`

### 1.3 分步执行逻辑

`run_factor_eval()` 内部按以下顺序执行，每一步调用 `factor_utils` 的已有函数。

---

#### Step 0：数据加载 + 股票池过滤

```python
from factor_utils import load_daily_panel

df = load_daily_panel(duckdb_path, start_date=start_date)
```

**然后根据 universe 过滤股票池：**

```python
if universe != "全市场":
    # 从 index_weight 加载成分股
    index_code = {"hs300": "000300.SH", "csi500": "000905.SH", "csi1000": "000852.SH"}[universe]
    members = _load_index_members(duckdb_path, index_code, start_date)
    # members: DataFrame with columns trade_date, ts_code
    # 注意：index_weight 表存的可能不是每个交易日都有数据（只在调仓日记录权重）
    # 需要 forward-fill：对于没有权重的交易日，沿用最近一个有权重的交易日的成分股名单
    df = _filter_by_index(df, members)
```

**⚠️ 容易出错：指数成分股的 PIT 处理**

`index_weight` 表的 `trade_date` 不是每个交易日都有记录——指数通常每月/每季度调仓，只有调仓日才写入。所以不能用简单的 merge on trade_date。

**正确做法：**
1. 获取所有需要评估的交易日列表
2. 对每个交易日，找到 ≤ 当日的最新 `index_weight` 日期
3. 用那个日期的成分股作为当日的股票池

```python
def _filter_by_index(df: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """用 index_weight 的 PIT 成分股过滤 df。
    
    members: trade_date 是调仓日，不是每个交易日都有。
    用 forward-fill 逻辑：每个评估日使用最近一次调仓日的成分股。
    """
    # 1. 获取所有调仓日（index_weight 里有的日期）
    rebalance_dates = sorted(members["trade_date"].unique())
    
    # 2. 对 df 里的每个 trade_date，找到 ≤ 该日期的最近调仓日
    eval_dates = sorted(df["trade_date"].unique())
    date_map = {}
    for d in eval_dates:
        prev = [r for r in rebalance_dates if r <= d]
        if not prev:
            continue
        date_map[d] = max(prev)
    
    # 3. 用调仓日的成分股去过滤对应评估日的股票
    filtered_parts = []
    for eval_date, rebal_date in date_map.items():
        codes = set(members[members["trade_date"] == rebal_date]["ts_code"])
        part = df[df["trade_date"] == eval_date]
        part = part[part["ts_code"].isin(codes)]
        filtered_parts.append(part)
    
    return pd.concat(filtered_parts, ignore_index=True)
```

---

#### Step 1：因子构造

```python
from factor_utils import compute_momentum

df = factor_func(df, **factor_kwargs)
```

**⚠️ 容易出错：因子构造后的 NaN**

不同因子有不同的缺失模式。`compute_momentum` 需要 20 日历史，前 19 天会是 NaN。后续 `build_factor` 和 universe filter 会处理，但不要在中间步骤 `dropna`，否则会丢掉整行。

---

#### Step 2：Forward Returns 计算

```python
from factor_utils import compute_forward_returns

ALL_HORIZONS = sorted({1, 5, 20} | set(range(1, 21)))  # 1~20 全部，IC decay 需要
df = compute_forward_returns(df, horizons=ALL_HORIZONS)
```

**⚠️ 容易出错：forward return 口径**

`compute_forward_returns` 的口径是 `adj_close[t+h+1] / adj_close[t+1] - 1`，即 T 日收盘后出信号，T+1 日开始持仓，持有 h 天。这个口径在 `factor_utils` 里已经写死了，不要改。

---

#### Step 3：样本过滤（universe mask）

```python
# 最短上市天数：要能算因子 + 最长 forward return 不缺失
FACTOR_WINDOW = factor_kwargs.get("window", 20)
MAX_HORIZON = 20
min_listing_days = FACTOR_WINDOW + MAX_HORIZON + 1

df["listed_trade_days"] = df.groupby("ts_code").cumcount() + 1

valid = (
    df["adj_close"].notna()
    & ~df["is_suspended"]
    & df["total_mv"].notna()
    & df["total_mv"].gt(0)
    & df["listed_trade_days"].ge(min_listing_days)
    & df[factor_kwargs["col_name"]].notna()
    & df["fwd_20d"].notna()
)
df["universe"] = valid
```

**⚠️ 容易出错：不能用当前最新股票列表回看历史。** `groupby("ts_code").cumcount()` 天然保证了这一点，因为它是按已有数据算的，不会引入未来的股票。

---

#### Step 4：因子预处理

```python
from factor_utils import build_factor, neutralize_by_size

df = build_factor(
    df,
    factor_col=factor_kwargs["col_name"],
    neutralization="industry_size",
    output_col="factor_industry_size_neutral",
)
df = neutralize_by_size(df, "factor_zscore", output_col="factor_size_neutral")

FACTOR_COL = "factor_industry_size_neutral"
FWD_COL = "fwd_5d"
```

预处理顺序：raw → winsorize(MAD) → zscore → neutralize(industry+size OR size only)。

---

#### Step 5：因子分布统计

```python
from factor_utils import cross_sectional_zscore, winsorize_mad

research_sample = df[df["universe"]]

cols = ["factor_raw", "factor_zscore", "factor_size_neutral", "factor_industry_size_neutral"]
labels = ["Raw", "Z-score", "Size-Neutral", "Industry+Size-Neutral"]

stats_rows = []
for col, label in zip(cols, labels):
    v = research_sample[col].dropna()
    stats_rows.append({
        "version": label,
        "count": len(v),
        "mean": v.mean(),
        "std": v.std(),
        "skew": v.skew(),
        "p01": v.quantile(0.01),
        "p99": v.quantile(0.99),
    })
distribution = pd.DataFrame(stats_rows)
```

---

#### Step 6：Rank IC + IC 衰减 + 半衰期

```python
from factor_utils import (
    compute_rank_ic, compute_ic_decay, ic_half_life, ic_summary,
)

# 主评估期的 IC
ic_df = compute_rank_ic(research_sample, FACTOR_COL, FWD_COL)
ic_summ = ic_summary(ic_df)

# IC 衰减
decay_df = compute_ic_decay(research_sample, FACTOR_COL, max_lag=20)

# 半衰期
half_life = ic_half_life(decay_df)
```

**⚠️ 容易出错：半衰期计算**

`ic_half_life` 的算法：取 `abs(horizon=1 的 mean_ic)` 作为初始值，找到第一个 `abs(mean_ic) < 初始值/2` 的 horizon。如果 20 期内都没衰减到一半，返回 `None`。注意用 `abs()`，因为 IC 可能为负（A 股动量因子就是负的）。

**⚠️ 容易出错：IC IR 的分母**

IC IR = mean_ic / std_ic。std_ic 用 `ddof=0`（总体标准差），不是样本标准差。`compute_rank_ic` 返回的 IC 已经是日频时序，计算 std 时不用再考虑自由度。

---

#### Step 7：分层收益 + 单调性判断

```python
from factor_utils import (
    assign_quantiles, compute_quantile_returns, rebalance_cumulative_returns,
)

df = assign_quantiles(df, FACTOR_COL, n_quantiles=5)
valid = df[df["universe"] & df["quantile"].notna() & df[FWD_COL].notna()]
q_summary, daily_q, q_pivot = compute_quantile_returns(valid, FWD_COL)
q_cum = rebalance_cumulative_returns(q_pivot, step=5)  # 每 5 天采样一次算累计
```

**单调性判断：**
```python
mean_returns = q_summary.set_index("quantile")["mean_return"]
if mean_returns.is_monotonic_increasing:
    is_monotonic = True
elif mean_returns.is_monotonic_decreasing:
    is_monotonic = False   # 方向反了
else:
    is_monotonic = None    # 中间组乱序
```

**⚠️ 容易出错：`rebalance_cumulative_returns` 的逻辑**

分层收益用的是**重叠的 forward returns**（每天都有未来 5 日收益），但累计曲线如果每天复合会导致重复计算。`rebalance_cumulative_returns` 只取每 step=5 天的观测点进行复合，中间点 forward fill。这和实盘每 5 天调仓一次的口径一致。

---

#### Step 8：多空收益

```python
from factor_utils import long_short_spread, ls_summary

ls = long_short_spread(q_pivot, step=5)
ls_summ = ls_summary(ls)
```

默认是多头 Q5 - 空头 Q1。如果因子方向是负的（IC < 0），`ls["spread"].mean()` 会是负的——这是正常的，评分卡里会如实展示。不要自动翻转方向。

---

#### Step 9：换手率

```python
# 每个分组的日换手率：当天出现在该分组的股票，有多少昨天不在
dates = sorted(df[df["universe"] & df["quantile"].notna()]["trade_date"].unique())
turnover_rows = []
for d1, d2 in zip(dates[:-1], dates[1:]):
    prev = df[(df["trade_date"] == d1) & df["quantile"].notna()]
    curr = df[(df["trade_date"] == d2) & df["quantile"].notna()]
    for q in range(1, 6):
        p_set = set(prev[prev["quantile"] == q]["ts_code"])
        c_set = set(curr[curr["quantile"] == q]["ts_code"])
        if len(c_set) > 0:
            turnover_rows.append({
                "trade_date": d2,
                "quantile": q,
                "turnover": 1 - len(p_set & c_set) / len(c_set),
            })
turnover_df = pd.DataFrame(turnover_rows)
t_summary = turnover_df.groupby("quantile")["turnover"].mean().reset_index()
mean_turnover = turnover_df["turnover"].mean()
```

**⚠️ 容易出错：分母用 c_set 还是 p_set？**

这里用 `len(c_set)`（当天数量）做分母。业内两种做法都有，但 `len(c_set)` 更常用（BigQuant 也用这个）。含义是：今天这组里有 x% 的股票是今天新进来的。如果用 `len(p_set)`，含义变成昨天这组里有 x% 今天出去了。

---

#### Step 10：逐年绩效拆解

```python
# 按年汇总 IC 和 Q5 收益
ic_df["year"] = ic_df["trade_date"].dt.year
q5_daily = q_pivot[5].dropna()  # Q5 组日收益

yearly_rows = []
for year, year_ic in ic_df.groupby("year"):
    year_dates = year_ic["trade_date"]
    year_q5 = q5_daily[q5_daily.index.isin(year_dates)]
    n_days = len(year_ic)
    yearly_rows.append({
        "year": year,
        "n_days": n_days,
        "mean_ic": year_ic["rank_ic"].mean(),
        "mean_return_q5": year_q5.mean(),
        "cum_return_q5": (1 + year_q5).prod() - 1,
        "win_rate": (year_ic["rank_ic"] > 0).mean(),
    })
yearly_perf = pd.DataFrame(yearly_rows).sort_values("year").reset_index(drop=True)
```

**⚠️ 容易出错：逐年绩效可能不完整**

如果 start_date 从年中开始，第一年只有半年数据。这是正常的，不要填 0 或做年化。表格里如实展示即可。另外如果某个年份样本太少（< 50 天），可以在评分卡里标 `*` 提示。

---

#### Step 11：评分卡

```python
ic_mean = ic_summ["mean_ic"]
ic_win = ic_summ["win_rate"]
ic_std = ic_summ["std_ic"]
ls_mean = ls_summ["mean"]
ls_cum = ls_summ["cum_return"]

scorecard = pd.DataFrame([
    ["Factor", factor_name, "-"],
    ["Universe", universe, "-"],
    ["N stocks", f"{df['ts_code'].nunique():,}", "-"],
    ["N dates", f"{ic_summ['n_days']:,}", "-"],
    ["Mean IC", f"{ic_mean:.4f}", "Pass" if ic_mean > 0 else "Weak"],
    ["IC IR", f"{ic_mean / ic_std:.3f}" if ic_std > 0 else "nan", "-"],
    ["IC Win Rate", f"{ic_win:.1%}", "Pass" if ic_win > 0.5 else "Weak"],
    ["IC Half-life", f"{half_life}d" if half_life else f">{20}d", "-"],
    ["Q1→Q5 Monotonic",
     "Yes" if is_monotonic else ("No" if is_monotonic is False else "Mixed"),
     "Pass" if is_monotonic else "Review"],
    ["Q5-Q1 Mean Spread", f"{ls_mean:.4%}", "Pass" if ls_mean > 0 else "Weak"],
    ["Q5-Q1 Cum Return", f"{ls_cum:.4%}", "Pass" if ls_cum > 0 else "Weak"],
    ["Mean Turnover", f"{mean_turnover:.1%}", "-"],
], columns=["Metric", "Value", "Judgement"])
```

**Judgement 的判断逻辑很简单：**
- `Pass`：方向对（正 IC、正 spread、单调）
- `Weak`：方向反了
- `Review`：不确定（如单调性 Mixed）
- `-`：中性指标，不做判断

---

## 二、`src/factor_eval/report.py` — 标准化图表

每张图都是一个独立函数，输入 `EvalResult`，返回 `matplotlib.figure.Figure`。函数内部自己调 `plt.subplots()`，不依赖全局状态。

**全局风格配置（所有图共享）：**

```python
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import numpy as np
import pandas as pd

# 统一调色板
COLORS = {
    "blue": "#4E79A7",
    "teal": "#2A9D8F",
    "green": "#59A14F",
    "orange": "#F28E2B",
    "red": "#E15759",
    "purple": "#B07AA1",
    "gray": "#6B7280",
}
QUANTILE_5 = [COLORS["blue"], COLORS["teal"], COLORS["gray"], COLORS["orange"], COLORS["green"]]

plt.rcParams.update({
    "figure.dpi": 120,
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "figure.titlesize": 13,
    "legend.fontsize": 9,
    "axes.unicode_minus": False,
    "axes.edgecolor": "#D0D5DD",
    "grid.color": "#D9DEE7",
    "grid.linewidth": 0.8,
})
```

### 2.1 `plot_distribution(result: EvalResult) -> plt.Figure`

**参考风格：** 01 notebook Step 1 的 4-in-1 直方图。这个风格已经很好，直接用。

- 4 个子图横向排列：Raw / Z-score / Size-Neutral / Industry+Size-Neutral
- 每张图：直方图 + 红色虚线标 mean + 深色竖线标 median
- 标题写 `{label}\nmean={:.3f}  std={:.3f}`
- figsize=(18, 4)
- 主标题 `Factor Distribution — {factor_name} ({universe})`

### 2.2 `plot_ic(result: EvalResult) -> plt.Figure`

**参考风格：** BigQuant + Alphalens 的 IC 时序图。

- 2×2 布局，figsize=(16, 8)：
  - 左上：日频 IC 柱状图 + 20 日滚动均线（橙色），参考 BigQuant 的 IC 时序叠加图
  - 右上：累计 IC 曲线 + 填充，参考 Alphalens 的 Cumulative IC
  - 左下：IC 分布直方图，标 mean 竖线
  - 右下：1d / 5d / 20d 三个 horizon 的 IC 均值柱状图，参考 BigQuant 的 Mean IC by Horizon
- 主标题 `IC Analysis — {factor_name} ({universe})`
- 使用 `ic_df` 和 `ic_decay_df`

**⚠️ 注意：** 右下角的柱状图，数据来自 `ic_decay_df` 里 horizon=1,5,20 的行，不是从 `ic_df` 重新算。确保两者一致。

### 2.3 `plot_ic_decay(result: EvalResult) -> plt.Figure`

**参考风格：** 华泰研报的 IC 衰减图。

- 单张图，figsize=(9, 4)
- 折线 + 散点：x=horizon, y=mean_ic
- 填充 ±1 std 的阴影带
- 灰色虚线标 0
- 标题下方加一行注解：`Half-life: {half_life}d` 或 `Half-life: >20d`
- `ax.set_xlabel("Forward Horizon (days)")`
- `ax.set_ylabel("Mean Rank IC")`

**⚠️ 注意：** 如果 IC 全为负，半衰期计算用的是 `abs(mean_ic)`，但图上画的是原始值（含符号），不要画绝对值。

### 2.4 `plot_quantile_returns(result: EvalResult) -> plt.Figure`

**参考风格：** Alphalens 的 Quantile Returns + BigQuant 的分层累计收益。

- 1×2 布局，figsize=(14, 5)：
  - 左：柱状图，5 组 mean return，柱子上标数值（百分比），颜色用 QUANTILE_5 渐变色
  - 右：5 条累计收益曲线，Q1 和 Q5 加粗，颜色同上
- 右图 y 轴用 `PercentFormatter`
- 主标题 `Quantile Returns — {factor_name} ({universe})`

### 2.5 `plot_long_short(result: EvalResult) -> plt.Figure`

**参考风格：** BigQuant 的多空收益图。

- 1×2 布局，figsize=(14, 5)：
  - 左：日频 spread 柱状图，正值绿色、负值红色
  - 右：累计 spread 曲线 + 绿色填充
- 标题标注 mean spread 和 final cumulative
- 主标题 `Long-Short (Q5-Q1) — {factor_name} ({universe})`

### 2.6 `plot_yearly_perf(result: EvalResult) -> plt.Figure`

**参考风格：** BigQuant 的年度绩效表 + 华泰的逐年对比思路。

- 单张图，figsize=(10, len(years) * 0.7)
- 用 `sns.heatmap` 或手写网格：行为年份，列为 mean_ic / cum_return_q5 / win_rate
- 更好的做法：3 个并排柱状图（每年一根柱子）：

```
fig, axes = plt.subplots(1, 3, figsize=(16, 4))
# [0]: Mean IC by Year（柱状图）
# [1]: Q5 Cumulative Return by Year（柱状图）
# [2]: IC Win Rate by Year（折线 + 50% 虚线）
```

- 主标题 `Yearly Performance — {factor_name} ({universe})`

### 2.7 `plot_scorecard(result: EvalResult) -> pd.io.formats.style.Styler`

**参考风格：** 01 notebook Step 6 的评分卡（已经在用了，直接用）。

- 返回 Styler 对象（notebook 里 `display()` 即可）
- 颜色规则和 01 一致：Pass=绿底，Weak=红底，Review=黄底，`-`=灰底
- 不需要包装成 `plt.Figure`，这是个表格不是图

---

## 三、`notebooks/02_single_factor_eval.ipynb`

### 3.1 结构

```
Cell 1 (markdown): 标题 + 一句话说明
Cell 2 (code): import + 初始化（路径、日期、调色板等）
Cell 3 (markdown): "## 全市场"
Cell 4 (code): result_all = run_factor_eval("mom_20d", compute_momentum, {"window": 20, "col_name": "mom_20d"}, DUCKDB_PATH, universe="全市场")
                plot_scorecard(result_all)
Cell 5 (code): plot_distribution(result_all); plot_ic(result_all); plot_ic_decay(result_all); ...
Cell 6 (markdown): "## 沪深300"
Cell 7 (code): result_hs300 = run_factor_eval(..., universe="hs300")
                plot_scorecard(result_hs300)
...（依次 csi500, csi1000）

Cell N (markdown): "## 跨市场对比"
Cell N+1 (code): 四张评分卡的关键指标拼成一张对比表
```

### 3.2 跨市场对比表

把四个 universe 的评分卡合成一张宽表：

```python
comparison = pd.DataFrame({
    "全市场": [result_all.scorecard[...], ...],
    "沪深300": [result_hs300.scorecard[...], ...],
    "中证500": [result_csi500.scorecard[...], ...],
    "中证1000": [result_csi1000.scorecard[...], ...],
}, index=["Mean IC", "IC IR", "IC Win Rate", "Half-life", "Monotonic", "Q5-Q1 Spread", "Mean Turnover"])
```

这是整个 02 notebook 最重要的一张表——一眼看出因子在不同市值段的差异。

### 3.3 其他要求

- 不要新手解读文字（那是 01 的事）
- 每个 universe 的图都出，但为了防止 notebook 太长，可以把图放在 `if SHOW_PLOTS:` 开关里
- `universe` 选项设个常量列表 `UNIVERSES = ["全市场", "hs300", "csi500", "csi1000"]`，方便以后改

---

## 四、容易忽略的坑（汇总）

1. **指数成分股是 PIT 的。** `index_weight` 不是每天都有，要 forward-fill。
2. **Forward return 不要用 T 日收盘价。** `factor_utils.compute_forward_returns` 已经处理好了（T+1 到 T+N+1），不要自己重写。
3. **IC 半衰期要用 abs。** A 股动量是反转，IC 为负，直接用原始值会出错。
4. **累计收益不要每天复合。** 重叠的 forward returns 要用 `rebalance_cumulative_returns` 只取调仓点的观测。
5. **换手率分母用当天数量。** 和 BigQuant 保持一致。
6. **单调性判断用 Pandas 的 is_monotonic_increasing。** 5 个数字手动比容易写出 bug。
7. **逐年绩效不完整是正常的。** 不要填充或年化，如实展示。
8. **`build_factor` 之前不要 dropna。** 中性化是横截面操作，跨股票做回归，drop 一行可能影响当天所有股票的残差。
9. **EvalResult 用 frozen=True。** 防止后续代码意外修改结果，导致复现问题。

---

## 五、验证清单

改完之后按这个 checklist 验证：

- [ ] `from factor_eval.runner import run_factor_eval, EvalResult` 不报错
- [ ] `result = run_factor_eval("mom_20d", compute_momentum, {"window": 20, "col_name": "mom_20d"}, DUCKDB_PATH, universe="全市场")` 跑完不报错
- [ ] `result.ic_summary["mean_ic"]` 和 01 notebook 的 IC 均值一致（允许微小浮点差异）
- [ ] `result.scorecard` 的 IC IR、胜率和 01 一致
- [ ] 6 个 plot 函数分别调用都能正常出图，不依赖 notebook 的全局变量
- [ ] 四个 universe 都跑通：全市场 / hs300 / csi500 / csi1000
- [ ] 02 notebook 从头到尾顺序执行不出错
- [ ] 跨市场对比表能清晰展示同一个因子在不同市值段的 IC 差异
