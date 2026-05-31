# A-share Data Foundation

本项目是 A 股日频数据底座，当前支持两类流程：

- 一期验证：最近若干交易日闭环采集、入库、构建 `daily_panel`、输出 DQ 报告。
- 历史补数：按日期范围分批采集，支持断点续跑、分区 raw、幂等入库和范围质检。

## 快速开始

```powershell
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

在 `.env` 中设置：

```env
TUSHARE_TOKEN=your_tushare_pro_token
```

## 一期验证

```powershell
python -m ashare_data.cli validate --days 5
```

## 历史补数

按日期范围采集：

```powershell
python -m ashare_data.cli ingest-history --start-date 20260501 --end-date 20260531
```

按滚动年份采集：

```powershell
python -m ashare_data.cli ingest-history --years 10
```

默认限速为 `180` 次/分钟。默认跳过 `ingest_status` 已成功且 raw 分区存在的数据；如需重拉：

```powershell
python -m ashare_data.cli ingest-history --start-date 20260501 --end-date 20260531 --force
```

范围构建 panel：

```powershell
python -m ashare_data.cli build-panel --start-date 20260501 --end-date 20260531
```

范围质检：

```powershell
python -m ashare_data.cli dq --start-date 20260501 --end-date 20260531
```

## 数据产物

- 分区 raw：`data/raw/<endpoint>/trade_date=YYYYMMDD/<endpoint>.parquet`
- 静态 raw：`data/raw/<endpoint>/<endpoint>.parquet`
- DuckDB：`data/warehouse/ashare.duckdb`
- 历史 DQ：`reports/dq/history_dq_<start>_<end>_<timestamp>.md`

## 质检内容

- 历史采集状态。
- 主键重复：`trade_date + ts_code`。
- 日期覆盖与缺口。
- 关键字段缺失率。
- OHLC 合理性。
- `daily` 与 `daily_basic` 覆盖差异。
- 申万历史行业归属匹配率。

历史 `history_dq` 报告验收时，至少应能看到以上 7 项检查章节标题。
