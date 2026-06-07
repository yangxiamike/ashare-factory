# 因子工厂 v1 评审修改

状态：已解决

## 背景

Codex 第一轮交付完成后，Mike 以多因子量化专家视角做了全面 review。核心量化逻辑正确，pipeline 可端到端跑通。以下是需要改的问题，按优先级排列。

---

## 一、YAML Parser 替换（高优先级）

**要改什么：** `src/ashare_factor/models.py` 里 187-295 行的手写 YAML parser（`parse_yaml_like` / `_parse_block` / `_parse_mapping` / `_parse_list` / `_parse_scalar` / `_strip_comment`）全部删掉。换成 `yaml.safe_load()`。

**为什么：** Plan 明确写了依赖 PyYAML，不需要手写。110 行代码 vs 一行 `yaml.safe_load()`。手写 parser 有多层嵌套的边界 case 处理不了（引号内冒号、科学计数法、多行字符串等）。

**涉及文件：**
- `models.py`：删 parser 函数，删 `load_yaml_like`
- `sample_builder/universe.py`：`load_yaml_like` → `yaml.safe_load`
- `factor_research/registry.py`：同上
- `factor_research/preprocessing.py`：同上
- `cli.py`：同上
- 确认 `PyYAML` 已在依赖中，没有就加上

**验收：** 现有 registry / universe / evaluation 三个 YAML 配置正常加载，`validate-registry` 和 `evaluate-factor` CLI 仍能跑通。

---

## 二、去掉 DAILY_PANEL_FIELDS 硬编码（高优先级）

**要改什么：** 删除 [models.py:10-59](src/ashare_factor/models.py#L10-L59) 的 `DAILY_PANEL_FIELDS` frozenset。改成运行时从 DuckDB `information_schema.columns` 动态读取可用的 daily_panel 字段。提供一个工具函数 `get_daily_panel_columns(duckdb_path)`。

**为什么：** 50+ 字段硬编码，daily_panel schema 每次变更都需要手动同步。当前唯一的调用方 `sample.py:198` 做 sanity check 可以直接对 DuckDB 检查。

**涉及文件：**
- `models.py`：删除 `DAILY_PANEL_FIELDS`
- `sample_builder/sample.py`：`_ensure_daily_panel_columns` 直接从 DuckDB 读 columns，不做 frozen set 对比
- `factor_research/registry.py`：`validate_registry` 的 `data_fields` 校验需要 columns 来源——可以接受一个 `available_columns: set[str]` 参数，由调用方传入

**验收：** `validate-registry` 仍能正确报告未知字段，不再依赖硬编码列表。

---

## 三、因子值入库 DuckDB（高优先级）

**要改什么：** 在 `data/warehouse/ashare.duckdb` 中新建 `factor_values` 表。evaluate 流程结束后把因子值写进去。表结构：

```sql
CREATE TABLE IF NOT EXISTS factor_values (
    trade_date       DATE    NOT NULL,
    ts_code          VARCHAR NOT NULL,
    factor_id        VARCHAR NOT NULL,
    value_raw        DOUBLE,
    value_processed  DOUBLE,
    PRIMARY KEY (trade_date, ts_code, factor_id)
);
```

**为什么：** 当前因子值只在 pipeline 内存中存在，evaluate 完就丢了。后续要跨因子 join、算相关性、做多因子组合都没法做。Plan 已经定义了长表契约，`library.py` 里 pivot/unpivot 转换也已写好。

**涉及文件：**
- 新增一个 `factor_store.py`（可放在 `factor_evaluation/` 或单独目录），提供 `write_factor_values(con_or_path, factor_df)` 和 `read_factor_values(con_or_path, factor_ids, start, end)`
- `evaluator.py` 或 `cli.py` 在 pipeline 末尾调用写入
- 写入用 DuckDB 的 `INSERT OR REPLACE`，按 `(trade_date, ts_code, factor_id)` 去重
- 可选：同步写入一份 Parquet 备份到 `data/factor_values/{factor_id}.parquet`

**验收：** evaluate 完一个因子后，能在 DuckDB 里直接查 `SELECT * FROM factor_values WHERE factor_id = 'momentum_20d_v1' LIMIT 10`。

---

## 四、评价指标入库 DuckDB（高优先级）

**要改什么：** 在 DuckDB 中新建评价相关的扁平表，替代纯 JSON 文件查询。建以下表：

```sql
-- 评价 run 元信息
CREATE TABLE IF NOT EXISTS evaluation_runs (
    run_id             VARCHAR PRIMARY KEY,
    factor_id          VARCHAR NOT NULL,
    evaluated_at       TIMESTAMP NOT NULL,
    status             VARCHAR NOT NULL,
    git_commit         VARCHAR,
    data_start_date    DATE,
    data_end_date      DATE,
    sample_row_count   INTEGER,
    primary_horizon    INTEGER
);

-- 核心指标（一行一个因子一次评价）
CREATE TABLE IF NOT EXISTS evaluation_metrics (
    run_id                  VARCHAR PRIMARY KEY,
    factor_id               VARCHAR NOT NULL,
    coverage_pct            DOUBLE,
    n_valid_dates           INTEGER,
    rank_ic_mean            DOUBLE,
    rank_ic_std             DOUBLE,
    rank_ic_ir              DOUBLE,
    rank_ic_t_stat          DOUBLE,
    rank_ic_win_rate        DOUBLE,
    rank_ic_skew            DOUBLE,
    rank_ic_kurtosis        DOUBLE,
    q5_q1_spread_mean       DOUBLE,
    top_quantile_return     DOUBLE,
    top_quantile_sharpe     DOUBLE,
    top_quantile_max_dd     DOUBLE,
    top_quantile_calmar     DOUBLE,
    long_short_sharpe       DOUBLE,
    mean_turnover           DOUBLE,
    turnover_std            DOUBLE,
    ic_half_life_lag        INTEGER
);

-- 分层收益
CREATE TABLE IF NOT EXISTS evaluation_quantiles (
    run_id       VARCHAR NOT NULL,
    factor_id    VARCHAR NOT NULL,
    quantile     INTEGER NOT NULL,
    mean_return  DOUBLE,
    hit_rate     DOUBLE,
    PRIMARY KEY (run_id, quantile)
);

-- IS/OOS 指标（复用 evaluation_metrics 结构，加一个 sample_period 字段区分 full_sample / in_sample / out_of_sample）
CREATE TABLE IF NOT EXISTS evaluation_period_metrics (
    run_id        VARCHAR NOT NULL,
    factor_id     VARCHAR NOT NULL,
    period        VARCHAR NOT NULL,  -- 'full_sample', 'in_sample', 'out_of_sample'
    rank_ic_mean  DOUBLE,
    rank_ic_ir    DOUBLE,
    -- ... 其他核心指标
    PRIMARY KEY (run_id, period)
);
```

**为什么：** 当前 `outputs/evaluation_results/*.json` 是深度嵌套 JSON，"找所有 RankIC > 0.03 的因子"需要读 N 个文件手动拼。进 DuckDB 后一条 SQL 搞定。

**涉及文件：**
- 新增或扩展 `factor_store.py` 加入 evaluation 写入逻辑
- `evaluator.py` evaluate 完后调用入库
- JSON 文件保留作为归档快照，不做查询主入口
- `factor_library.json` 可以保留不动，或者从 evaluation_metrics 表取每个 factor 最新 run 即可替代

**验收：**
```sql
SELECT factor_id, rank_ic_mean, rank_ic_ir 
FROM evaluation_metrics 
WHERE rank_ic_mean > 0.03 
ORDER BY rank_ic_ir DESC;
```
能正确返回结果。

---

## 五、DuckDB 路径正确传递（中优先级）

**要改什么：** `cli.py` evaluate-factor 流程中，`settings.duckdb_path` 需要一路传到 `evaluator.evaluate_factor`。当前 `duckdb_path` 参数默认 None，导致 evaluator 拿不到路径，`data_snapshot` 里 `duckdb_path` 为 null。

**涉及文件：**
- `cli.py:_run_factor_pipeline`：把 settings.duckdb_path 传给 `_call_public("evaluate_factor", ..., duckdb_path=...)`
- `evaluator.py:evaluate_factor`：正确使用传入的 duckdb_path

**验收：** 跑 evaluate-factor 后，输出 JSON 和 report 的 `data_snapshot.duckdb_path` 不再为 null。

---

## 六、Noise Baseline 实现（中优先级）

**要改什么：** 当前 `metrics.py:compare_with_baselines` 在没有 baseline_input 时只返回 placeholder。需要在 evaluate 流程中实际计算 noise baseline 因子（`random_normal`、`random_uniform`、`random_by_date_shuffle`），把它们的评价指标喂给 `compare_with_baselines`。

具体实现：
- 新增 `baseline.py`（放在 `factor_evaluation/` 下）
- 三个 noise baseline：
  - `random_normal`：每个截面生成标准正态随机数作为因子值
  - `random_uniform`：每个截面生成均匀分布随机数
  - `random_by_date_shuffle`：把真实因子值按日期打乱（保持每天截面分布不变，破坏时间序列结构）
- 只算 rank_ic_mean / top_quantile_return / sharpe / max_drawdown / mean_turnover / oos_rank_ic_mean，不需要全量评价
- 每个 noise baseline 跑多次（比如 10 次），取指标的分布

**为什么：** 当前 gate 的 `stronger_than_most_noise_baselines` 因 baseline 全是 placeholder 而永远无法满足，`active` 状态永不触发。

**涉及文件：**
- 新增 `factor_evaluation/baseline.py`
- `evaluator.py` 或 `cli.py` pipeline 中插入 baseline 计算步骤
- simple technical baseline（reversal_1d、momentum_60d 等）可以用已有 builtin 因子 + 注册表跑，但第一版可以先只做 noise baseline

**验收：** evaluate 一个 factor 后，baseline_comparison 的 noise 组不再显示 placeholder，gate 的 `stronger_than_most_noise_baselines` 能正确返回 true/false。

---

## 七、其他小修

### 7.1 universe.yaml 默认 min_amount 说明
`universe.yaml` 里 `min_amount: 1000` 注释清楚是千元单位，等价于 100 万元。当前 CLI `_load_sample_config` 的 dual-path parse 也有一份 fallback 默认值 `1_000_000.0`——删掉 fallback 路径，只保留 `universes` 解析。

### 7.2 报告里中性化顺序补充说明
`report.py:_render_markdown` 的 Notes 部分把 "Neutralization ordering is assumed..." 改成具体说明：
"预处理顺序为 winsorize(MAD, n=3) → cross-sectional zscore → industry+size regression residual → re-standardize。中性化发生在 zscore 后，回归 beta 反映的是标准化因子值与行业/市值的关系。"

### 7.3 preprocessing 的 NaN/constant 检查
`preprocessing.py:37-40` 的检查保留，但在 `invalid` reason 里补充实际覆盖率数值，方便排查。

---

## 验收总览

- [ ] `models.py` 不再包含手写 YAML parser 和 DAILY_PANEL_FIELDS
- [ ] `yaml.safe_load()` 加载所有配置文件正常
- [ ] `factor_values` 表已建，evaluate 后数据入库可查
- [ ] `evaluation_runs` / `evaluation_metrics` / `evaluation_quantiles` 表已建，evaluate 后指标入库可查
- [ ] `duckdb_path` 正确出现在 data_snapshot 中
- [ ] noise baseline 实际计算，gate `stronger_than_most_noise_baselines` 非 placeholder
- [ ] universe.yaml 的 min_amount 有清晰注释
- [ ] Markdown 报告 Notes 解释了中性化顺序
- [ ] 三个 demo 因子仍能正常 evaluate
- [ ] CLI 四个命令均无回归

---

## Codex 最终方案

- 已按原建议去掉手写 YAML parser，并切到 `yaml.safe_load()`。
- 已删除 `DAILY_PANEL_FIELDS`，改成从 DuckDB `information_schema.columns` 动态读取 daily_panel 字段。
- 已新增 `factor_store.py`，把 `factor_values`、`evaluation_runs`、`evaluation_metrics`、`evaluation_quantiles`、`evaluation_period_metrics` 写入 DuckDB。
- 已在 evaluate 流程里补上 noise baseline（`random_normal`、`random_uniform`、`random_by_date_shuffle`），让 gate 的 `stronger_than_most_noise_baselines` 不再卡在 placeholder。
- `simple_technical` baseline 本轮继续保留占位。这一点与任务文件允许的“第一版可以先只做 noise baseline”一致，原因是先把 `active` 的阻塞项解开，同时避免把 builtin 因子递归跑评估链路一起卷进这次修复。
- `duckdb_path` 已改成由 CLI 统一 resolve 后透传到 evaluator，不再出现 `data_snapshot.duckdb_path = null`。
- `universe.yaml` 已补千元单位注释，CLI 侧也删掉了旧格式 fallback，只保留 `universes` 配置结构。
