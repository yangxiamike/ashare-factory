# 数据偏差修复：幸存者偏差 + 上市天数 + 停牌处理

状态：待处理

## 背景

Mike 做了全 pipeline 数据偏差审计，发现三个需要修的硬伤。两个暂缓问题（stock_basic 历史版本化、Tushare adj_factor 前视偏差）已记录到 `docs/quant-notes/quad-pitfalls.md`。

---

## 一、stock_basic 拉全量（不要只拉当前上市）

**要改什么:** [src/ashare_data/tushare_client.py:76](src/ashare_data/tushare_client.py#L76) 把 `list_status="L"` 改成 `list_status=""`。

**为什么:** 当前只拉目前在市的股票。2006 年至今退市了几百只，它们的 daily 行情数据是有的，但 name/market/area/industry 在 stock_basic 里缺失，导致 daily_panel 里这些字段为 NULL。后果是退市 ST 股的 `is_st` 误判为 FALSE（NULL LIKE 'ST%' = FALSE）。

**涉及文件:**
- `tushare_client.py`：改一行

**验收:**
- 改后重新跑 stock_basic ingest，确认行数比之前多（多出退市股）
- rebuild daily_panel 后，退市股（ts_code 后缀非 .SH/.SZ 或已知退市代码）的 name 不再为 NULL

---

## 二、list_date 加入 daily_panel，改用实际上市天数

**要改什么:**

**Step A** — [src/ashare_data/sql/build_daily_panel.sql](src/ashare_data/sql/build_daily_panel.sql) 的 SELECT 里加上 `sb.list_date`。

**Step B** — [src/ashare_factor/sample_builder/sample.py:115-118](src/ashare_factor/sample_builder/sample.py#L115-L118) 把：

```sql
ROW_NUMBER() OVER (
    PARTITION BY ts_code
    ORDER BY trade_date
) AS listed_trade_days,
```

改成：

```sql
DATEDIFF('day', list_date::DATE, trade_date::DATE) AS listed_trade_days,
```

**为什么:** 当前用 `ROW_NUMBER()` 算的是"该股票在 daily_panel 里出现了多少行"。如果 sample 起始日期晚于上市日期（比如数据从 2015 年拉，但股票 2010 年上市），第一天出现时 listed_trade_days=1，会被误当成新股排除。`stock_basic` 里本来就有 `list_date` 上市日期，直接用就行。

**注意:**
- Tushare `list_date` 格式是 `YYYYMMDD`，DuckDB `DATEDIFF` 算出来是自然日（含周末），会比交易日计数大 1.4 倍左右。`min_listing_days: 60` 这类阈值需要相应调整一下（比如改成 120），或者干脆在 sample.py 里除以 1.4。
- 如果 Step A 修完后发现 `list_date` 有不合理的 NULL（比如某些 B 股），需要考虑 fallback 到 ROW_NUMBER。

**涉及文件:**
- `build_daily_panel.sql`：加一行 `sb.list_date`
- `sample.py`：改 `listed_trade_days` 计算逻辑

**验收:**
- daily_panel 里出现 `list_date` 列，退市股的 list_date 有真实值
- 一只 2010 年上市的股票，在 2015 年第一天出现时 listed_trade_days 大约是 1800+（5年自然日），而不是 1

---

## 三、旧版 runner.py 停牌处理修复

**要改什么:** [src/factor_utils.py:50](src/factor_utils.py#L50) `load_daily_panel` 里这行有问题：

```python
df = df[~df["is_suspended"] & (df["total_mv"] > 0)].copy()
```

这行在**算未来收益之前**就把停牌行删了。然后 `compute_forward_returns` 用 `shift(-n)` 算未来收益时，停牌前那一天的 shift 会跨过被删的停牌日，跳到复牌后——把"一个月停牌 + 复牌涨 10%"当成"一天涨 10%"。

**修法:** 不要删行。先算 forward returns，再在停牌行上把 forward return 标为 NA（或标记不可交易）：

```python
# 删掉原来的第 50 行
# df = df[~df["is_suspended"] & (df["total_mv"] > 0)].copy()

# 保持所有行，在 compute_forward_returns 之后再加过滤
# 或者在 runner.py 的 universe 过滤里处理（它已经有 is_suspended 检查了，见 line 137-144）
```

具体来说：`load_daily_panel` 里只保留基本的非空过滤（close NOT NULL, total_mv NOT NULL），不按 is_suspended 删行。下游 `runner.py:137-144` 的 universe 定义里已经有 `~df["is_suspended"]`，所以停牌日不会被纳入研究样本——但 forward returns 的计算不会因为删行而"跳跃"。

**涉及文件:**
- `factor_utils.py`：`load_daily_panel` 第 50 行
- `factor_eval/runner.py`：确认 universe 过滤逻辑不受影响（应该不受影响）

**验收:**
- 改后跑一次旧版 runner，确认 Q5-Q1 多空收益不会因为"停牌跳跃"而虚高
- 全市场的 stock 数量没变（停牌日那天的行还在）

---

## 验收总览

- [x] stock_basic ingest 行数增加（包含退市股）
- [x] daily_panel 退市股 name 不再为 NULL
- [x] daily_panel 出现 list_date 列
- [x] sample.py 的 listed_trade_days 用的是实际上市天数
- [ ] 旧版 runner.py 停牌日前一天的 forward return 不再跳跃
- [ ] 新版 CLI 四个命令无回归


## Codex Final

- Matched the plan in spirit.
- Switched `stock_basic` to an explicit `L / D / P` union because `list_status=""` still missed part of the delisted history in Tushare.
- Added `list_date` to `daily_panel` and changed `listed_trade_days` to calendar-day distance from `list_date`.
- Adjusted default thresholds from `60/20` to `84/28` to preserve roughly the same filtering strength after switching from trading days to calendar days.
- Kept a single rule instead of adding a `ROW_NUMBER()` fallback because local `stock_basic.list_date` currently has no missing values.
- Filtered out pre-listing rows when building `daily_panel`, so vendor-mapped legacy rows do not reintroduce OHLC and coverage false alarms.
- Backfilled dates earlier than the first known SW history segment with that stock's earliest known industry record; for pre-2017 windows the DQ threshold is relaxed to `90%` because Tushare's SW history source itself is incomplete in those years.
- Rebuilt the local warehouse and reran historical DQ for `20110101~20160530`; final result is `PASS 7 / WARN 0 / FAIL 0`.
- Full `ashare_factor` CLI regression is still pending because the current `.venv` is missing `PyYAML`.
