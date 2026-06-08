# Tushare 历史采集优化计划

## 背景

当前 A 股日频历史采集仍保留“按交易日拉全市场”的策略：

```text
交易日 × 日频接口
```

这个策略适合横截面因子研究，因为每天天然需要完整股票截面。本轮不改成“按股票拉多日数据”。

当前主要优化目标不是减少核心行情 API 口径，而是减少重复请求、本地 DuckDB 小批量写入和状态检查开销。

## 不做的改动

- 不改变 `daily / adj_factor / daily_basic / suspend_d / stk_limit` 按交易日拉全市场的主口径。
- 不引入无限并发请求，避免触发 Tushare 限流。
- 不把日频采集和 `daily_panel` 逻辑混在一起重构。

## 待办 1：静态表一次任务只拉一次

### 问题

`ingest-history-verbose` 按月切分历史区间时，会多次调用 `ingest_history`。

如果每个月都重复拉：

```text
stock_basic
index_classify
index_member_all
```

就会产生无意义的 API 请求。

这些表会更新，但同一次历史补数任务里反复拉没有必要。

### 目标

- 历史补数任务开始时拉一次静态表。
- 每个月 chunk 只处理日频接口。
- 普通非 verbose 的 `ingest_history` 仍保持完整闭环，默认会刷新静态表。

### 注意

`index_member_all` 带 `in_date / out_date`，有历史区间信息；不能把它当作“无历史意义的当前快照”。这里只是避免同一任务重复拉。

## 待办 2：批量读取采集状态

### 问题

当前跳过逻辑逐个检查：

```text
endpoint + trade_date
```

历史区间越长，DuckDB 查询次数越多。

### 目标

- 任务开始时一次性读取目标区间内成功采集状态。
- 在内存里用 set 判断是否跳过。
- 保留 raw parquet 是否存在的校验，避免只有状态没有文件。

## 待办 3：复用 DuckDB 连接

### 问题

当前每拉完一个 `endpoint + trade_date`，就执行一次：

```text
写 raw parquet
delete DuckDB 当日旧数据
insert DuckDB 新数据
写 ingest_status
```

每次 DuckDB 操作（`has_successful_ingest` / `upsert_trade_date_table` / `record_ingest_status`）都独立开/关一次连接。TODO 2 做完后状态读取的连接开销消失，但写入侧仍有大量重复连接。

### 方案

不改变 per-date 的写入粒度，而是让 `ingest_history` 在整个任务生命周期内复用同一个 DuckDB 连接：

- `storage.py` 的 `upsert_trade_date_table` / `record_ingest_status` / `replace_table` 加可选 `con` 参数。
- 有 `con` 时直接用，没有时自己开连接（向后兼容）。
- `ingest_history` 在函数入口开一个 connection，传给所有写操作。

### 为什么不做批量 insert

- per-date 粒度在失败时定位清晰：哪天挂了只影响那天。
- 批量 insert 后一个日期失败要回滚整批或写补偿逻辑，复杂度上去了收益不大。
- 连接复用已经解决了主要浪费。

### 原则

- raw parquet 仍按日期分区保存，方便断点续跑和排查。
- 失败的日期仍能单独记录。

## 待办 4：补充退市状态字段

### 问题

当前 `stock_basic` 会按 `L / D / P` 拉取上市、退市、暂停上市股票，但落库字段没有保存状态本身。

这会导致后续只能知道“这只股票存在于 stock_basic”，但不知道它是：

```text
上市
退市
暂停上市
```

### 目标

给 `stock_basic` 补字段：

```text
list_status
delist_date
```

如果 Tushare 当前接口不直接返回 `delist_date`，先保存 `list_status`，再单独确认退市日期来源。

### 影响

- 更容易识别幸存者偏差。
- 更容易解释股票在样本中消失的原因。
- 为后续样本边界和 DQ 检查留基础字段。

## 建议实施顺序

1. 静态表一次任务只拉一次。
2. 批量读取采集状态。
3. 批量入库。
4. 补 `stock_basic.list_status / delist_date`。

## 验收

- 现有测试通过。
- 历史补数 resume/skip 行为不变。
- force 重拉行为不变。
- raw parquet 分区结构不变。
- DuckDB 表结果行数和原口径一致。
- `stock_basic` 能区分 `L / D / P` 状态。
