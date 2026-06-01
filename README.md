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

首次使用时，建议先初始化本地仓库文件：

```powershell
python -m ashare_data.cli init
```

## 本地数据怎么准备

本项目默认把数据产物放在本地 `data/` 目录下，不需要也不建议放进 Git。

- 原始分区数据会落到 `data/raw/`
- 本地 DuckDB 会落到 `data/warehouse/ashare.duckdb`
- 质检报告会落到 `reports/dq/`

如果是新环境，通常按下面顺序准备数据：

1. 先配置好 `.env` 里的 `TUSHARE_TOKEN`
2. 跑一次小范围验证，确认环境、接口和落盘都正常
3. 再按需要补历史数据
4. 最后构建 `daily_panel` 并跑 DQ

最小验证命令：

```powershell
python -m ashare_data.cli validate --days 5
```

如果只是把仓库 clone 到新电脑，`git pull` 不会带下本地 `parquet` 和 `duckdb` 数据文件；需要在本机重新拉取，或手动把已有的 `data/` 目录拷过来。

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

## 常用复用流程

### 1. 新电脑首次启动

```powershell
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m ashare_data.cli init
python -m ashare_data.cli validate --days 5
```

### 2. 正式补历史数据

```powershell
python -m ashare_data.cli ingest-history --years 10
python -m ashare_data.cli build-panel --start-date 20160101 --end-date 20260531
python -m ashare_data.cli dq --start-date 20160101 --end-date 20260531
```

### 3. 已有数据，继续补最近一段

```powershell
python -m ashare_data.cli ingest-history --start-date 20260501 --end-date 20260531
python -m ashare_data.cli build-panel --start-date 20260501 --end-date 20260531
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

## README 维护原则

这个 README 主要维护“怎么用”而不是“怎么开发”，后续新增命令或调整数据流程时，优先同步更新下面几类信息：

- 快速开始是否仍然可直接跑通
- 数据准备步骤是否有变化
- 常用复用流程里的命令是否还是当前推荐口径
- 数据产物路径是否有变化
