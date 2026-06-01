# 01 Notebook 改进点（给 Codex）

以下 4 个问题来自 Claude Code review，由 Codex (Cursor AI) 执行修改。

---

## Issue 1: notebook 里重定义了 `factor_utils.py` 已有函数

**位置**：`notebooks/01_single_factor_mvp.ipynb` cell `33635d13`

**问题**：`compute_momentum`、`compute_forward_returns`、`winsorize_mad`、`cross_sectional_zscore`、`neutralize_by_size`、`assign_quantiles` 在 `src/factor_utils.py` 里已经有几乎一样的实现。notebook 重新定义了一遍，两套代码容易分叉。

**修改**：把 notebook 里的函数定义替换为直接 import：

```python
from factor_utils import (
    load_daily_panel,
    compute_momentum,
    compute_forward_returns,
    winsorize_mad,
    cross_sectional_zscore,
    neutralize_by_size,
    assign_quantiles,
    build_factor,
)
```

注意 `factor_utils.py` 里 `compute_momentum` 产出的列名是 `"mom"`，而 notebook 用的是 `"mom_20d"`。统一为一个列名，或者给函数加 `col_name` 参数。

`factor_utils.py` 里还有 `build_factor()` 函数直接封装了 winsorize → zscore → neutralize 的完整管线，可以直接用。

---

## Issue 2: 没有行业中性化

**位置**：`notebooks/01_single_factor_mvp.ipynb` cell `33635d13` 和 Step 0 markdown

**问题**：只做了市值中性化。A 股板块轮动很强，比如 momentum 可能只是在买一个热门行业。标准做法是做 行业+市值 联合中性化——用因子对行业哑变量 + log(市值) 回归，取残差。

**修改**：

在 `factor_utils.py` 或 notebook 里新增函数：

```python
def neutralize_by_industry_and_size(df, factor_col, industry_col="sw_l1_name"):
    df = df.copy()
    df["factor_neutral"] = np.nan
    for _, g in df.groupby("trade_date"):
        mask = (g["total_mv"].notna() & (g["total_mv"] > 0)
                & g[factor_col].notna() & g[industry_col].notna())
        if mask.sum() < 10:
            continue
        industry_dummies = pd.get_dummies(g.loc[mask, industry_col], drop_first=True).astype(float)
        X = np.column_stack([
            np.ones(mask.sum()),
            np.log(g.loc[mask, "total_mv"].values),
            industry_dummies.values,
        ])
        y = g.loc[mask, factor_col].values
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ beta
        resid = (resid - resid.mean()) / resid.std(ddof=0)
        df.loc[g.index[mask], "factor_neutral"] = resid
    return df
```

然后将 Step 0-6 的主因子列从 `"factor_neutral"`（仅市值中性）切换为行业+市值联合中性化的版本。在评分卡里对比两个版本的差异。

注意：`load_daily_panel` 需要把 `sw_l1_name` 也加进 SELECT 列表。

---

## Issue 3: 缺少 IC decay 分析

**位置**：`notebooks/01_single_factor_mvp.ipynb` Step 2 IC 分析

**问题**：只对比了 1d/5d/20d 的 mean IC 柱状图，但没有看 IC 的自相关衰减结构。IC decay 告诉你因子的预测力能持续多久，直接决定最优调仓频率。

**修改**：在 Step 2 末尾或 Step 5 附近加一段 IC decay 分析：

```python
# IC decay: IC(t, t+k) for k=1..N
from scipy import stats

def compute_ic_decay(df, factor_col, max_lag=20):
    """Compute mean IC for forward horizons 1..max_lag."""
    records = []
    for h in range(1, max_lag + 1):
        fwd_col = f"fwd_{h}d"
        if fwd_col not in df.columns:
            continue
        ic_vals = []
        for dt, g in df[df.universe].groupby("trade_date"):
            valid = g[[factor_col, fwd_col]].dropna()
            if len(valid) < 10:
                continue
            ic = valid[factor_col].rank().corr(valid[fwd_col].rank())
            ic_vals.append(ic)
        if ic_vals:
            records.append({"horizon": h, "mean_ic": np.mean(ic_vals),
                          "std_ic": np.std(ic_vals), "ic_ir": np.mean(ic_vals) / np.std(ic_vals)})
    return pd.DataFrame(records)

decay_df = compute_ic_decay(df, FACTOR_COL, max_lag=20)

# 图标：horizon vs mean_ic，带 error band
fig, ax = plt.subplots(figsize=(8, 4))
ax.plot(decay_df["horizon"], decay_df["mean_ic"], color=COLORS["blue"], linewidth=2, marker="o")
ax.fill_between(decay_df["horizon"],
                decay_df["mean_ic"] - decay_df["std_ic"],
                decay_df["mean_ic"] + decay_df["std_ic"],
                color=COLORS["blue"], alpha=0.15)
ax.axhline(0, color="gray", linestyle="--", linewidth=0.8)
ax.set_title("IC Decay by Horizon")
ax.set_xlabel("Forward Horizon (days)")
ax.set_ylabel("Mean Rank IC")
plt.tight_layout()
plt.show()
```

---

## Issue 4: 回测做了但不够落地

**位置**：`notebooks/01_single_factor_mvp.ipynb` Step 7

**问题**：
- 只算了单边成本，实盘买入+卖出要扣双边（`2 * turnover * cost`）
- 没有做 Q5 内部的市值加权版本对比（等权 vs 市值加权结论可能不同）
- 没有涨跌停过滤：如果调仓日某只 Q5 股票涨停，第二天买不到，收益就会被虚增

**修改**：

1. 双边成本：把 `net_return = gross_return - 2 * turnover * one_way_cost`
2. 市值加权版本：加一个 `weighted_return = selected[FWD_COL].mul(selected["total_mv"]).sum() / selected["total_mv"].sum()`
3. 涨跌停过滤：在 `load_daily_panel` 或 backtest 里加一列 `is_limit_up`，如果 next_day 开盘即涨停则从组合中剔除

```python
# 在研究回测中加市值加权对比
gross_ew = selected[FWD_COL].mean()               # 等权
gross_vw = (selected[FWD_COL] * selected["total_mv"]).sum() / selected["total_mv"].sum()  # 市值加权

# 双边成本
net_return = gross_return - 2 * turnover * one_way_cost  # 双边
```

不需要模拟滑点和真实成交，保持"轻量研究型"定位，但双边成本和市值加权对比是最小必要改动。

---

## 优先级

建议按 Issue 1 → Issue 2 → Issue 3 → Issue 4 顺序改，每个改完跑一遍 notebook 确认不变形。

---

*来源：Claude Code review，2026-06-01*

## Codex 最终方案

与原建议不完全一致。

- `5447159` 已把 4 个 issue 主体全部落地：notebook 复用 `factor_utils`、主因子切到行业+市值联合中性化、补上 IC decay，并把轻量回测改成双边成本 + 等权/市值加权 + 涨停过滤。
- 后续 `4510f45` 又额外补了 Step 1.5 / Step 2.5 的 5 项补充检验，这是超出原任务单范围的增强，不影响本任务已完成的判断。
