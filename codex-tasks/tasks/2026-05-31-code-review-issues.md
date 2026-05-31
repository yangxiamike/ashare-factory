# Code Review Issues — Tushare → DuckDB 管线

## 高优先级

### 1. SQL 注入 — `src/factor_utils.py` `load_daily_panel`
f-string 拼 `start_date`，应改为 parameterized query。

### 2. 双重 rate limiter 拉低吞吐量
`ingest_history` 的 `RateLimiter` 默认 180/min，`TushareClient._wait_for_slot()` 也固定 180/min，两层各等一遍，等效 ~90 calls/min。`ingest_history` 默认 `rate_limit_per_minute` 应改为 0，统一用 client 内部 limiter。

### 3. `ingest_recent` 对日频表做全量 `CREATE OR REPLACE TABLE`
如果 DuckDB 已有历史数据，`ingest_recent` 会静默丢掉所有历史行。加个 guard 或改用 upsert。

## 中优先级

### 4. `build_daily_panel` 增量模式 schema 变更直接报错
已有数据时 schema 不匹配就抛异常，只能全量重建。

### 5. `ingest_history` `row_counts` 口径不一致
全部被 skip 的 endpoint 不会出现在 `row_counts` 里，只在 `skipped` 里。

### 6. `_panel_select_sql` 用 `.format()` 拼 SQL 参数
SQL 文件如有其他 `{}` 会炸，改用 `:param` 或更安全的占位符。

## 低优先级

### 7. `__init__.py` 不暴露公共 API
### 8. 两套 rate limiter 重复实现 (`TushareClient._wait_for_slot` vs `ingest.RateLimiter`)
### 9. `_migrate_warehouse_schema` DDL 用 f-string 拼标识符
### 10. `create_tables.sql` 无 PRIMARY KEY / UNIQUE 约束
### 11. `EXPECTED_COLUMNS` 和 `TEXT_COLUMNS` 高度重叠，维护两套 schema 定义
