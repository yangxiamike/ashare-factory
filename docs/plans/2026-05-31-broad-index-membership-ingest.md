# 宽基指数成分补数计划

## 任务名

补一套宽基指数成分/权重数据链路，供后续因子检测选择股票池使用。

## 目标

- 支持采集沪深 300、中证 500、中证 1000、上证 50 等宽基指数成分。
- 把宽基成分/权重落到本地 raw Parquet 和 DuckDB。
- 支持按日期区间补历史，也支持后续日常增量补数。
- 保持入库幂等：同一指数、同一交易日重复跑，不产生重复记录。
- 第一版只做数据层，不改因子 Notebook，不把宽基字段强行写进 `daily_panel`。

## 当前范围

默认宽基指数：

- `000300.SH`：沪深 300
- `000905.SH`：中证 500
- `000852.SH`：中证 1000
- `000016.SH`：上证 50

可选扩展：

- `399006.SZ`：创业板指
- `000688.SH`：科创 50

数据源：

- Tushare Pro
- 优先使用 `index_weight` 接口，因为它既能表达成分，也能保留权重。

## 实现思路

1. 增加宽基指数代码常量
   - 建议集中定义 `BROAD_INDEX_CODES`。
   - 不要把指数代码散落在 CLI、ingest、测试里。

2. 增加 Tushare 客户端接口
   - 在 `src/ashare_data/tushare_client.py` 增加 `index_weight(index_code, start_date, end_date)`。
   - 参数保持和实际调用链一致，不为不存在场景提前放宽类型。

3. 增加存储 schema
   - 在 `src/ashare_data/sql/create_tables.sql` 增加 `index_weight` 表。
   - 在 `src/ashare_data/storage.py` 的 `EXPECTED_COLUMNS` / 类型配置里增加同名 schema。
   - 建议字段：
     - `index_code`
     - `con_code`
     - `trade_date`
     - `weight`

4. 增加入库函数
   - 新增按 `index_code + trade_date` 覆盖写入的 upsert 函数。
   - 不复用只按 `trade_date` 删除的 `upsert_trade_date_table`，避免不同指数之间互相删数据。

5. 增加采集函数
   - 在 `src/ashare_data/ingest.py` 增加 `ingest_index_weight(...)` 或 `ingest_broad_index_weights(...)`。
   - 默认遍历 `BROAD_INDEX_CODES`。
   - 对每个指数、每个日期区间拉取 `index_weight`。
   - 写 raw，再写 DuckDB。
   - 记录 `ingest_status`，endpoint 建议用 `index_weight`，trade_date 可用实际 `trade_date`，必要时把 `index_code` 编进 raw 路径。

6. 增加 CLI
   - 在 `src/ashare_data/cli.py` 增加命令：

```powershell
python -m ashare_data.cli ingest-index-weight --start-date 20200101 --end-date 20260531
```

可选参数：

- `--index-code 000300.SH`
- `--index-code 000905.SH`
- `--force`

7. 暂不改 `daily_panel`
   - 因子研究侧可以按需 join：

```sql
SELECT p.*
FROM daily_panel p
JOIN index_weight w
  ON p.trade_date = w.trade_date
 AND p.ts_code = w.con_code
WHERE w.index_code = '000300.SH'
```

这样一个研究任务可以自由选择沪深 300、中证 500、中证 1000，或组合多个股票池。

## 主要产物

- 新表：`index_weight`
- 新 raw 分区目录：`data/raw/index_weight/...`
- 新 CLI 命令：`ingest-index-weight`
- 新 TushareClient 方法：`index_weight`
- 新 storage upsert 函数：按 `index_code + trade_date` 覆盖
- 对应单元测试

## 验收标准

- 可以指定日期范围拉取宽基指数权重/成分。
- DuckDB 中 `index_weight` 有数据。
- 同一个 `index_code + trade_date` 重跑后记录数不翻倍。
- 多个指数同一天数据可以共存，互不覆盖。
- raw 文件能落地，并且路径能区分不同指数。
- 测试通过：

```powershell
python -m pytest
```

## 风险和注意点

- Tushare `index_weight` 可能对积分/权限有要求，失败时要把错误记录到状态或清晰抛出。
- 不同指数的数据发布日期可能滞后，日常增量建议回看最近若干交易日，而不是只拉当天。
- 如果接口返回字段超过预期，只保留当前需要字段，避免 schema 多处重复维护。
- 第一版不要顺手改因子 Notebook 或 `daily_panel`，避免把数据层和研究层耦合太早。
- 如果后续要做“指数历史成分区间”，可以从 `index_weight` 按交易日推导，不建议第一版额外造第二张几乎重复的成分表。
