# 项目地图

这份文档写给夏董快速看项目用。

它不讲复杂技术细节，只回答两个问题：

- 这个项目里有什么？
- `src` 里的文件大概是干嘛的？

## 项目目录总览

- `src/`：正式代码。数据采集、入库、建表、质检、因子研究工具都放这里。
- `data/`：本地数据目录。包括原始 Parquet 数据和 DuckDB 数据库，一般不提交到 Git。
- `notebooks/`：研究和验证过程。适合做探索、跑样例、看图表。
- `reports/`：输出报告目录。比如数据质量检查报告，一般是运行代码后生成的结果。
- `docs/`：项目说明、计划和工作记录。以后项目怎么管，主要看这里。
- `tests/`：测试代码。用来检查核心代码有没有被改坏。
- `codex-tasks/`：任务材料区。Claude / DeepSeek 写给夏董看的任务材料，由夏董转给 Codex 执行。

## `src` 代码说明

### `src/ashare_data/`

A 股数据底座代码。

主要负责从 Tushare 拉数据，保存原始数据，写入 DuckDB，生成 `daily_panel`，再做数据质量检查。

### `src/ashare_data/cli.py`

命令行入口。

平时运行 `init`、`ingest`、`ingest-history`、`build-panel`、`dq`、`validate` 这些命令，都是从这里进来。

### `src/ashare_data/config.py`

项目配置。

负责读取 `.env`、Tushare token、本地数据目录、DuckDB 路径等。

### `src/ashare_data/constants.py`

常量文件。

目前主要放宽基指数代码，比如沪深 300、中证 500、中证 1000 等。

### `src/ashare_data/tushare_client.py`

Tushare 客户端。

负责真正调用 Tushare API，并处理接口限速。

### `src/ashare_data/ingest.py`

数据采集主流程。

负责拉最近数据、历史数据、指数权重数据，并把结果交给存储层保存。

### `src/ashare_data/storage.py`

数据存储层。

负责写 Parquet、写 DuckDB、建表、更新表、记录采集状态。

### `src/ashare_data/panel.py`

面板数据构建。

负责把各类原始表合成研究用的 `daily_panel`。

### `src/ashare_data/dq.py`

数据质检。

负责检查缺失、重复、日期覆盖、价格合理性等，并输出 Markdown 质检报告。

### `src/ashare_data/sql/create_tables.sql`

建库建表 SQL。

定义 DuckDB 里需要的基础表。

### `src/ashare_data/sql/build_daily_panel.sql`

构建 `daily_panel` 的 SQL。

负责把行情、复权、估值、停牌、涨跌停、行业等数据拼到一起。

### `src/ashare_data/__init__.py`

Python 包标记文件。

让 `ashare_data` 可以作为一个包被导入。

### `src/factor_utils.py`

单因子研究工具。

负责读取 `daily_panel`、计算动量因子、算未来收益、做标准化 / 中性化、分组、IC、分层收益等。它更偏研究分析，不是数据采集底座。

### `src/ashare_data_foundation.egg-info/`

Python 自动生成的安装信息目录。

它不是业务代码，不用维护，平时可以忽略。
