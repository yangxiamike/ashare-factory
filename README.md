# A-share Data Foundation

这是一个 A 股日频数据底座项目。

当前已补齐的数据质检模块，目标是把 `daily`、`daily_basic`、`daily_panel` 这几张核心表的基础质量问题先暴露出来，并把结果写成 Markdown 报告，方便人工扫读。

## 当前能力

- 初始化、拉取、组装面板的 CLI 骨架已经预留在 `src/ashare_data/cli.py`
- 数据质检入口已经可接入：`ashare-data dq`
- 质检报告会输出到 `reports/dq/`

## 质检内容

- 主键重复：默认检查 `ts_code + trade_date`
- 日期覆盖：汇总最小日期、最大日期、交易日数量，并可校验预期交易日
- 关键字段缺失率：检查 `daily`、`daily_basic`、`daily_panel` 中存在的关键字段
- OHLC 合理性：检查 `high >= open/close/low`、`low <= open/close`，并识别空值
- `daily` 与 `daily_basic` 覆盖差异：找出只存在于单边的主键记录
- 行业历史归属匹配率：按 `in_date/out_date` 区间检查日频记录能否匹配行业历史

## 使用方式

1. 安装依赖

```bash
pip install -e .[dev]
```

2. 准备环境变量

参考 `.env.example`，至少补齐 Tushare token 和本地数据目录。

3. 运行质检

```bash
ashare-data dq
```

如果主流程里已经知道本次应该覆盖哪些交易日，也可以在代码里调用：

```python
from ashare_data.dq import run_quality_checks

report_path = run_quality_checks(settings, expected_trade_dates=["20240527", "20240528"])
print(report_path)
```

## 测试

```bash
pytest
```

## 集成说明

- 当前 `dq.py` 只依赖 `settings.duckdb_path`
- 如果主工程后续提供 `settings.report_dir`、`settings.reports_dir` 或 `settings.project_root`，报告目录会自动跟随
- 行业历史表默认优先识别 `index_member_all`，其次识别 `stock_industry_history`
