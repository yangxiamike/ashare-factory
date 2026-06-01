# 累积收益复利错误 & 相关修复

状态：待处理

## 背景

Claude Code 对 `notebooks/01_single_factor_mvp.ipynb` 做了深度 review，发现核心 bug：**把重叠的 5 日收益当成不重叠的 1 日收益来复利**，导致累积收益虚高数十倍。

---

## 🔴 Issue 1（严重）：分层累积收益重叠复利

**根因**：`fwd_5d` 是 5 日收益，相邻两天窗口重叠 4/5：
```
Day 1 fwd_5d: 覆盖 Day 2 → Day 7
Day 2 fwd_5d: 覆盖 Day 3 → Day 8   ← 与 Day 1 重叠 4 天
```

### 1a. `factor_utils.py` `long_short_spread()` 函数

**文件**：`src/factor_utils.py` Line 282

```python
# 当前（错误）
ls["cum_spread"] = (1 + ls["spread"].fillna(0)).cumprod() - 1
```

`spread` 列的值是 fwd_5d 的 Q5-Q1 差值。519 个重叠日当独立日收益复利。

**修复**：加一个 `step` 参数，只对非重叠调仓日复利。例如 stride=5：

```python
def long_short_spread(pivot, step=5):
    ls = pd.DataFrame({
        "trade_date": pivot.index,
        "spread": pivot.get(5, 0) - pivot.get(1, 0),
    })
    ls["cum_spread"] = np.nan
    ls.iloc[::step, ls.columns.get_loc("cum_spread")] = (
        1 + ls["spread"].fillna(0).iloc[::step]
    ).cumprod().values - 1
    ls["cum_spread"] = ls["cum_spread"].ffill()
    return ls
```

或者直接只保留调仓日的行再 cumprod，返回时 index 对齐。

### 1b. Notebook Step 3 Cell 10 分层累积收益

**文件**：`notebooks/01_single_factor_mvp.ipynb` cell `39199b17`

```python
# 当前（错误）
q_cum = (1 + q_pivot.fillna(0)).cumprod() - 1
```

**修复**：只取每 5 个交易日的行做 cumprod，然后 ffill 对齐：

```python
step = 5
q_cum = (1 + q_pivot.fillna(0).iloc[::step]).cumprod() - 1
q_cum = q_cum.reindex(q_pivot.index).ffill()
```

### 1c. Notebook Step 4 Cell 12 直接计算

**文件**：`notebooks/01_single_factor_mvp.ipynb` cell `4996df50`

```python
# 当前（错误）
s = ls["spread"].dropna()
cum = (1 + s).cumprod()
dd = (cum / cum.cummax() - 1)
```

这里直接对 spread 做了 cumprod 来算 cum_return 和 max_drawdown。改用 `ls["cum_spread"]`（修复后的）来算 drawdown，或者同样取 stride=5。

---

## 🔴 Issue 2（严重）：记分卡传播了错误的累积值

**文件**：`notebooks/01_single_factor_mvp.ipynb` cell `8eebe563`

这些变量和列全部来自 `long_short_spread()` 的错误输出：
- `ls_cum = ls["cum_spread"].iloc[-1]` → 记分卡 `Long-short cumulative`
- `neutralization_compare` 表里的 `q5_q1_cum_return` 列

修复 Issue 1a 后这里自动修正，不需要额外改动。但需要重跑确认数值合理。

---

## 🟡 Issue 3：IC 观测值重叠

**位置**：`factor_utils.py` `compute_rank_ic`，notebook Step 2

**问题**：每日 IC 用 fwd_5d 计算，相邻 IC 因为收益窗口重叠 4/5 而高度自相关。519 个观测值并非独立样本。

**影响**：
- `std_ic` 被低估（序列太平滑）
- `IC IR = mean_ic / std_ic` 绝对值被高估
- `mean_ic` 和 `win_rate` 不受影响

**修复（可选，不改也行）**：在记分卡或 IC summary 里加一个 stride=5 的 IC IR 作为对比：

```python
ic_ind = ic_df.iloc[::5]["rank_ic"]  # 独立观测
print(f"IC IR (overlapping): {ic_df['rank_ic'].mean() / ic_df['rank_ic'].std():.3f}")
print(f"IC IR (independent): {ic_ind.mean() / ic_ind.std():.3f}")
```

如果两个值差距很大（>30%），说明重叠引入了显著偏差。

---

## 🟢 Issue 4（小优化）：`compute_forward_returns` 命名

**文件**：`src/factor_utils.py` Line 69-76

当前公式：`s.shift(-(h+1)) / s.shift(-1) - 1`

- `fwd_1d` 实际是 t+1→t+2 的一日收益，不是"下一日收益"
- 避开了 look-ahead，但命名会让人误解

**不需要改公式**（逻辑正确），建议在 docstring 里说明：

```python
def compute_forward_returns(df, horizons=(1, 5, 20)):
    """Compute forward returns avoiding same-day look-ahead.
    
    fwd_{h}d = adj_close[t+h+1] / adj_close[t+1] - 1
    i.e., h-day return starting from t+1 (one day after factor observation).
    """
```

---

## 验收方式

- [ ] Step 3 右图 Y 轴不再显示 3000%+ 的累积收益，而是一个合理的值（100%-200% 量级）
- [ ] Step 4 Q5-Q1 累积价差从 -80.9% 变成 -27% 左右
- [ ] Step 6 记分卡 `Long-short cumulative` 不再显示 -80.9061%
- [ ] 修复后 `long_short_spread` 仍然兼容现有调用方
- [ ] notebook 从头跑到尾不报错
- [ ] 如果做了 Issue 3，IC IR 对比数字打印在 Step 2 输出里

---

## 预计影响

| 指标 | 修复前（错误） | 修复后（正确） |
|---|---|---|
| Q1 累积收益 | ~4000% | ~110% |
| Q5 累积收益 | ~780% | ~54% |
| Q5-Q1 累积价差 | -80.9% | ~-27% |
| Q5-Q1 max drawdown | -88.3% | ~-35% |

---

*来源：Claude Code deep review，2026-06-01*

## Codex 最终方案

与原建议一致。
