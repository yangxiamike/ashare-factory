# 单因子 MVP — 三个数据/逻辑修复

下面的问题已经确认，直接改，不要问我确认。改完做一个 commit。

---

## 背景

`notebooks/01_single_factor_mvp.ipynb` 对 A 股 20 日动量做了单因子检验。流程框架正确，但有三处需要修复。

---

## 1. 复权 — `load_daily_panel` 和所有用 `close` 的地方改用后复权价

**问题**：当前 `load_daily_panel` 的 SELECT 只取 `close`（原始收盘价），没有取 `adj_factor`。动量因子 `close_t / close_{t-20} - 1` 和未来收益 `close_{T+6} / close_{T+1} - 1` 用原始价格计算，会被分红除权、送转股的虚假价格跳变污染。

**验证**：实测原始 close 和复权 close 的 IC 相关性 0.999，当前样本期内对因子排序影响很小，但严谨起见必须修正，尤其是个别 `adj_factor` 差异大的股票（如 920821.BJ 的 adj_factor 达 2.94，复权前后动量差 80%）。

**改法**：

### 1a. `src/factor_utils.py` → `load_daily_panel`

SQL 里加上 `adj_factor`：
```sql
SELECT trade_date, ts_code, close, adj_factor, total_mv, is_suspended, sw_l1_name
FROM daily_panel
```

然后新增一列：
```python
df["adj_close"] = df["close"] * df["adj_factor"]
```

### 1b. `src/factor_utils.py` → `compute_momentum`

把 `close` 改成 `adj_close`：
```python
df["mom"] = df.groupby("ts_code")["adj_close"].transform(
    lambda s: s / s.shift(window) - 1
)
```

### 1c. `src/factor_utils.py` → `compute_forward_returns`

同样改用 `adj_close`：
```python
df[f"fwd_{h}d"] = df.groupby("ts_code")["adj_close"].transform(
    lambda s: s.shift(-(h + 1)) / s.shift(-1) - 1
)
```

### 1d. `notebooks/01_single_factor_mvp.ipynb`

把所有 cell 里的 `close` 替换为 `adj_close`。当前 notebook 里在 `compute_momentum`、`compute_forward_returns`、`valid` 过滤条件中引用了 `close`，都改掉。

---

## 2. 新股过滤 — 排除上市不足窗口期+1 天的股票

**问题**：新上市股票的历史数据不足 `FACTOR_WINDOW + max(FORWARD_HORIZONS)` 个交易日。当前没有过滤，导致：
- 上市不满 20 天的股票，`mom_20d` 计算时会跟 IPO 前的数据对齐（或得到 NaN/异常值）
- 例如 `688585.SH` 的 `mom_20d` 达到 1354%，显然不是真实动量信号

**改法**：

### 2a. `src/factor_utils.py` → `load_daily_panel`

在函数最后、`return` 之前加新股过滤。对每只股票，第一个有效交易日后至少需要 `min_history` 天才进入样本：

```python
min_history = 20 + 20 + 1  # FACTOR_WINDOW + max(FORWARD_HORIZONS) + 1
df["_first_date"] = df.groupby("ts_code")["trade_date"].transform("min")
df = df[df["trade_date"] >= df["_first_date"] + pd.Timedelta(days=min_history)].copy()
df = df.drop(columns=["_first_date"])
```

用 `Timedelta` 而非交易日计数是因为 `load_daily_panel` 不依赖具体的 factor window 参数，用日历日做一个宽松过滤即可。更精确的交易日级过滤可以在 notebook 里根据实际 factor 参数做。

### 2b. `notebooks/01_single_factor_mvp.ipynb`

在 `valid` 条件里加一条（可选，如果 factor_utils 已经做了这里就跳过）：

```python
min_trading_days = FACTOR_WINDOW + max(FORWARD_HORIZONS) + 1
df["_stock_days"] = df.groupby("ts_code").cumcount() + 1
valid = valid & (df["_stock_days"] >= min_trading_days)
```

---

## 3. 评分卡 — 单调性判断支持反向单调

**问题**：当前评分卡（Step 6）只检查 `is_monotonic_increasing`。但 A 股 20 日动量在当前样本里呈完美的**反向单调**（Q1 > Q2 > Q3 > Q4 > Q5），只显示"否"会让读者误以为因子没有排序能力，实际上是有显著的负向排序能力。

**改法**：

### 3a. `notebooks/01_single_factor_mvp.ipynb` → 评分卡 cell

把单调性检查改成三态：

```python
mean_returns = q_summary["mean_return"].values
if pd.Series(mean_returns).is_monotonic_increasing:
    monotonic_str = "正向单调"
    monotonic_judge = "通过（正因子）"
elif pd.Series(mean_returns).is_monotonic_decreasing:
    monotonic_str = "反向单调"
    monotonic_judge = "通过（负因子/反转）"
else:
    monotonic_str = "否"
    monotonic_judge = "待看"
```

评分卡里的对应行改为使用 `monotonic_str` 和 `monotonic_judge`。

---

## 改完后的 commit

```
fix: adj_close, IPO filter, and monotonicity check in factor pipeline
```

把 `src/factor_utils.py` 和 `notebooks/01_single_factor_mvp.ipynb` 放在一个 commit 里。
