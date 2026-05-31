# 单因子检验下一步规划（来自 Claude Code）

## 背景

`notebooks/01_single_factor_mvp.ipynb` 已经跑通了 `mom_20d` 的单因子检验闭环，从真实 DuckDB 数据读取到评分卡输出，流程完整。

现在需要从"单因子演示"进到"批量因子检验 + 因子注册入库 + 宽基分层评价"。

## 当前状态

- `src/factor_utils.py` 已有稳定的工具函数（load、因子构造、预处理、IC、分层收益、多空、稳定性）
- 01 notebook 重新定义了同名函数，和 `factor_utils.py` 重复
- 只做了市值中性化，没有行业中性化
- 只跑了一个因子、全样本、没有和宽基做对比

## 下一步目标

### 直接做：`notebooks/02_factor_batch.ipynb`

这个 notebook 回答一个问题：同一套检验流程能不能复用在不同因子上，结果能不能入库。

内容：

1. **直接用 `factor_utils.py`**，不再 notebook 里重定义函数
2. **新增行业中性化函数**（`neutralize_by_industry_and_size`），在 `factor_utils.py` 或 notebook 里定义
3. **批量跑 3 个因子**：
   - `mom_20d`：20日价格动量
   - `turnover_20d`：20日日均换手率
   - `volatility_20d`：20日收益率波动率
4. **每个因子输出 2 套评分卡**：
   - 全样本
   - 沪深300 成分股限定
5. **把因子值写入 DuckDB**：
   - 新表 `factor_values`（trade_date, ts_code, factor_name, raw_value, zscore_value, neutral_value）
   - 新表 `factor_registry`（factor_name, category, formula, params, created_at）
6. **关键对比图表**：三个因子的 IC 均值对比柱状图、分层收益对比

### 第二优先：因子入库与注册

等 02 notebook 跑通后，开始建库表：

```sql
-- 因子注册表
CREATE TABLE factor_registry (
    factor_id INTEGER PRIMARY KEY,
    factor_name VARCHAR UNIQUE,
    category VARCHAR,       -- momentum / liquidity / risk / value ...
    display_name VARCHAR,
    formula TEXT,
    params JSON,
    created_at DATE
);

-- 因子值表（截面存储）
CREATE TABLE factor_values (
    trade_date DATE,
    ts_code VARCHAR,
    factor_name VARCHAR,
    raw_value DOUBLE,
    zscore_value DOUBLE,
    neutral_value DOUBLE,
    PRIMARY KEY (trade_date, ts_code, factor_name)
);

-- 因子评价表（日频 IC）
CREATE TABLE factor_eval_daily (
    factor_name VARCHAR,
    trade_date DATE,
    horizon INTEGER,
    rank_ic DOUBLE,
    n_stocks INTEGER,
    PRIMARY KEY (factor_name, trade_date, horizon)
);
```

### 第三优先：脚本化

等 02 notebook 跑通且表结构稳定后，把核心流程抽到 `src/factor_eval/`：

```
src/
  factor_eval/
    __init__.py
    factor_runner.py    # 单个因子的计算+检验主流程
    registry.py         # 因子注册表读写
    storage.py          # 因子值/评价结果写入 DuckDB
    report.py           # 评分卡输出
```

CLI 入口示例：

```bash
python -m factor_eval.run --factor mom_20d --start 20240101
python -m factor_eval.run --factor turnover_20d --start 20240101 --benchmark hs300
```

## 全样本 vs 宽基限定的定位

| 维度 | 全样本 | 宽基限定（沪深300/中证500/中证1000） |
|------|--------|--------------------------------------|
| 目的 | 因子的全市场统计效力 | 因子的可投资域验证 |
| 优点 | 样本大、统计显著 | 排除小市值/流动性偏差 |
| 缺点 | 包含大量不可交易小票 | 样本小、部分因子不显著 |
| 用途 | 主检验 | 回测前的必要性检查 |
| 存放 | 全样本评分卡 | 分宽基的 IC 对比表 |

建议的做法：
- 主检验用全样本，保证统计效力
- 报告中附带分宽基的 IC 对比（沪深300 / 中证500 / 中证1000 / 中证2000）
- 回测部分用宽基限定，更接近实盘

## 不做什么

- 不做因子合成 / 多因子模型
- 不做完整组合优化
- 不做正式交易回测系统
- 不做机器学习因子挖掘
- 不做 dashboard

## 风险和注意点

- 行业中性化需要历史行业归属数据，确认 `sw_l1_name` 在 daily_panel 里是否为 PIT（Point-in-Time）
- 宽基指数成分股变动需要 PIT，确认 `index_weights` 表是否已有历史数据
- 因子入库前先确认字段名和类型，避免后续返工
- `factor_utils.py` 和 notebook 的函数差异需要统一（notebook 版有些细节可能和 src 版不同）

---

*来源：Claude Code 对话，2026-06-01*
