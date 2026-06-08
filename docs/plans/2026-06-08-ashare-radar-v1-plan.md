# A股 Market Radar V1 实施计划

## 1. 当前口径

本项目不拆成多个 repo，也不新开长期 radar 分支。

`ashare_data`、`ashare_factor`、`ashare_radar` 都属于同一个 A股工程仓库，统一复用现有共享数据库：

```text
data/warehouse/ashare.duckdb
```

本阶段先做 radar 的计划、数据盘点、最小代码骨架和 smoke tests。不要一次性实现完整新闻系统、完整日报系统或自动化交易逻辑。

## 2. 目录命名

正式 Python 包统一命名为：

```text
src/ashare_radar/
```

计划材料继续沿用项目既有记录规则，放在：

```text
docs/plans/
```

后续建议结构：

```text
docs/
└── plans/
    └── 2026-06-08-ashare-radar-v1-plan.md

src/
└── ashare_radar/

configs/
└── ashare_radar/

reports/
└── ashare_radar/
```

说明：

- `docs/plans/`：放需求、计划和阶段性设计。
- `src/ashare_radar/`：放正式 Python 模块。
- `configs/ashare_radar/`：放 radar 专用规则配置。
- `reports/ashare_radar/`：放每日 radar markdown 报告。
- radar 中间数据后续可放在 `data/ashare_radar/`，不进 Git。

## 3. 与现有数据底座的关系

`ashare_radar` 只读 `ashare_data` 产出的共享数据，不复制、不重建数据库。

优先读取 `daily_panel`：

- 日频行情：`pct_chg`、`close`、`pre_close`、`amount`
- 市值与估值：`total_mv`、`circ_mv`、`pe_ttm`、`pb`
- 换手与量能：`turnover_rate`、`turnover_rate_f`、`volume_ratio`
- 涨跌停：`up_limit`、`down_limit`
- 停牌：`is_suspended`
- 申万行业归属：`sw_l1_code`、`sw_l1_name`

当前先视为缺口：

- 申万一级行业指数日行情
- 自动新闻源稳定采集
- 完整 LLM provider 调用

第一版行业强弱先使用行业内个股聚合收益近似，不强依赖申万行业指数行情。

## 4. 第一阶段最小闭环

第一阶段只完成这些事情：

1. 检查当前仓库结构。
2. 检查 DuckDB 表、`daily_panel` 字段和数据覆盖。
3. 输出数据具备情况和字段缺口。
4. 创建最小代码骨架。
5. 创建最小 CLI：

```powershell
python -m ashare_radar.cli daily --date YYYY-MM-DD
python -m ashare_radar.cli news --date YYYY-MM-DD
```

6. 为每个模块补一个 smoke test。

## 5. 模块设计

### 5.1 data_input

职责：

- 读取共享 DuckDB。
- 校验 `daily_panel` 必要字段。
- 按日期输出标准化 market frame。

第一版不要做数据修补。如果字段缺失，要明确报错。

### 5.2 market_temperature

职责：

- 计算市场温度分数。
- 输出 `risk_on / neutral / risk_off`。

第一版使用规则打分，不做机器学习。

核心指标：

- 指数或市场平均涨跌幅
- 成交额相对 5 日均值变化
- 上涨家数 / 下跌家数
- 涨停 / 跌停数量
- 个股收益分化度

### 5.3 style_factor_ranking

职责：

- 用现有字段构造粗粒度风格分组。
- 输出风格收益排名。

第一版风格可先粗糙，但必须配置化。

候选风格：

- 大盘 / 小盘：`total_mv`
- 价值 / 成长近似：`pb`、`pe_ttm`
- 高股息：`dv_ratio`
- 高换手：`turnover_rate`
- 低价股：`close`
- 动量 / 反转：后续可用短期收益扩展

### 5.4 industry_strength_ranking

职责：

- 判断申万一级行业强弱。
- 输出强势 Top 5、弱势 Bottom 5、放量 Top 5 和行业扩散度。

第一版使用 `daily_panel.sw_l1_name` 聚合个股收益。

`industry_return_method` 先写为：

```text
stock_aggregate
```

### 5.5 news_intake

职责：

- 跑通最小新闻流水线。

第一版先支持：

- mock news
- manual news
- clean
- dedup
- keyword relevance filter
- rule based structure
- rank

不要求实时新闻流，不要求全网抓取。

### 5.6 report_generator

职责：

- 汇总市场温度、风格排名、行业排名和新闻结果。
- 生成 markdown 日报。

报告只做市场状态判断，不写具体买卖建议。

## 6. 第一阶段不做

- 不做自动交易。
- 不做买卖建议。
- 不做完整回测。
- 不做复杂多 Agent 辩论。
- 不做 Trader Agent。
- 不做 Portfolio Manager Agent。
- 不做向量数据库。
- 不做前端 dashboard。
- 不把 radar 和因子工厂强绑定。
- 不重建 A股数据底座。

## 7. 测试计划

新增 `tests/ashare_radar/`。

最小测试：

- `data_input`：DuckDB 路径和 `daily_panel` 字段校验。
- `market_temperature`：mock 行情输出 score/state。
- `style_factor_ranking`：mock 风格分组输出排序。
- `industry_strength_ranking`：mock 行业数据输出强弱行业。
- `news_intake`：mock news 跑 clean/dedup/filter/rank。
- `report_generator`：mock 结构化结果生成 markdown。

验收命令：

```powershell
pytest tests/ashare_radar
```

## 8. 后续提交策略

每完成一个独立小任务做一次 commit。

建议拆分：

1. `docs: add ashare radar plan`
2. `feat: scaffold ashare radar modules`
3. `test: add ashare radar smoke tests`
4. `feat: add daily radar cli skeleton`

当前这一步只保存计划材料，先给夏董审阅。
