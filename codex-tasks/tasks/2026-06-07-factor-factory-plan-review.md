# 因子工厂 v1 方案文档 review 改进

状态：已解决

## 背景

Mike 和 Claude 一起 review 了 `docs/plans/2026-06-07-factor-factory-v1-four-module-plan.md`，对照现有 `src/factor_utils.py` 和 `src/factor_eval/` 的实际代码后，提出了以下改进点。请按优先级逐项落地到方案文档中。

---

## P0 — 影响评价结果正确性，必须改

### 1. 可交易 mask 补全过滤条件

当前 plan 的 sample_builder 只有：停牌、主板过滤、上市交易日。需要补：

- [ ] **涨跌停过滤**：涨停无法买入（多头端），跌停无法卖出（空头端）。现有 `factor_utils.py` 已经有 `next_open_is_limit_up` 逻辑，直接纳入 `universe.py` 的可交易 mask
- [ ] **ST / *ST 过滤**：从 `stock_basic` 表或 `name` 字段匹配，排除 ST 股
- [ ] **流动性过滤**：日成交额 < 阈值（如 100 万）的样本标记为不可交易，阈值写进 `universe.yaml`
- [ ] **新股过滤**：除了 `min_listing_days`，前 N 个交易日（如 20 天）因"炒新效应"数据特征异常，单独标记可选过滤

### 2. forward return 在 t+1 停牌时的处理

当前公式 `adj_close[t+h+1] / adj_close[t+1] - 1` 隐含假设 t+1 日可以成交。实际中 t+1 日停牌时：

- [ ] `adj_close[t+1]` 虽然是前一日收盘价（复权后连续），但该日实际无法以该价格买入
- [ ] 这条记录的 forward return 应标记为 NaN，**不是静默计算一个有偏值**
- [ ] 同理，t+h+1 日停牌也会让 forward return 偏零，同样标记 NaN
- [ ] 在 `forward_returns.py` 和 plan 文档中明确这个处理

### 3. 因子方向 (direction) 的语义和使用

`FactorSpec` 里有 `direction: str` 字段，但 plan 没有说明：

- [ ] 明确 direction 取值：`"positive"`（因子值越大预期收益越高）vs `"negative"`（因子值越大预期收益越低）
- [ ] 评价系统如何使用 direction：IC 预期为正的因子，IC 为负算失败；预期为负的因子，IC 为正算失败。gate 判断和 reasons 需要考虑 direction
- [ ] `builtins.py` 里 reversal 因子的实现需要和 direction 一致：reversal_5d 的 direction 是 negative，因子值 = -short_term_return，这样 IC 期望为正

---

## P1 — 评价结论的统计可靠性和可复现性

### 4. IC 统计补全

现有 `ic_summary` 只输出 mean_ic, std_ic, ic_ir, win_rate。补充：

- [ ] **IC t-statistic**：`mean_ic / (std_ic / sqrt(n_days))`，判断 IC 是否统计显著
- [ ] **正负 IC 天数比**：不是只看 >0 的比例，也看 <-1 std 的极端负 IC 天数占比
- [ ] **IC 偏度和峰度**：判断分布是否存在肥尾

### 5. Rolling Window 稳定性分析

- [ ] **Rolling 12-month mean IC**：滑动窗口 252 天的 IC 均值序列，用来判断因子是否在"失效中"
- [ ] **换手率标准差 `turnover_std`**：现有代码只有 `mean_turnover`，加一个 std 判断量化分组稳定性
- [ ] plan 文档验收标准里补上这两项

### 6. 评价结果可复现性

`evaluation_result.json` 需要记录：

- [ ] `daily_panel` 的数据快照：date range (min/max trade_date)、row count、DuckDB 文件路径
- [ ] `git_commit`：`git rev-parse HEAD`
- [ ] 配置文件 hash（registry / universe / evaluation yaml 的 md5）
- [ ] `EvaluationResult` dataclass 加对应的 `data_snapshot` 和 `code_version` 字段

### 7. 因子值长表 vs 宽表的数据契约

plan 提到输出长表 `trade_date / ts_code / factor_id / factor_value_raw`，但现有代码全是宽表操作。需要明确：

- [ ] **内部计算用宽表**（pandas 向量化，每个因子一列）
- [ ] **入库持久化用长表**（`factor_id + trade_date + ts_code` 复合索引，DuckDB 查询友好）
- [ ] **`factor_library.py` 负责 pivot/unpivot 转换**
- [ ] plan 文档 Code Structure 部分注明这个设计决策

### 8. 技术栈：statsmodels vs lstsq 分工

plan 笼统说用 statsmodels，实际需要区分：

- [ ] **中性化场景**（每天截面回归）：用 `np.linalg.lstsq`，不需要 statsmodels 的完整推断开销
- [ ] **回归检验场景**（`compute_factor_return_t`，需要正确的 t 值）：用 `statsmodels.OLS`
- [ ] plan Tech Stack 部分说明两者各用在哪

---

## P2 — 更完整的因子画像和运营设计

### 9. Gate 设计：Hard Gate（一票否决） + Soft Gate（加权打分）

当前 plan 的 gate 设计过于模糊，需要明确的复合规则。详见下方完整 YAML 草案。

Hard gate 是准入条件，任何一条失败 → rejected：
- `mean_rank_ic > 0`（确认方向正确）
- `coverage_pct > 0.3`（样本偏差不能太大）
- `n_valid_dates > 60`（统计需要最低样本量）

Soft gate 用加权打分区分 active vs watch。权重和 scoring 阈值见下方草案，核心设计：
- [ ] 每个指标映射到 0-10 分，**线性插值**在阈值间补全
- [ ] 加权总分：`score >= 6.5` → active，`4.0 - 6.5` → watch，`< 4.0` → rejected
- [ ] 不同因子类别 (momentum / reversal / volatility) 支持 category override 调整权重
- [ ] `GateDecision.reasons` 记录每个指标的分数和失败原因

### 10. factor_library 状态管理和因子注册表分离

- [ ] `factor_registry.yaml` 中 `status` 字段**永远等于 "candidate"**——注册表是静态因子定义，走 git，人工维护
- [ ] `factor_library.json` 是状态的唯一权威来源，机器生成，每次 evaluate 后更新
- [ ] 状态四态 → 五态：`candidate → active / watch / rejected`，加 **`archived`**（曾经有效但市场结构变化导致失效）
- [ ] `factor_library.json` 结构包含最近一次评价摘要（状态 + mean_rank_ic + ic_ir + sharpe + turnover），方便下游模块快速浏览

### 11. 交易表现指标

现有 `factor_eval/runner.py` 已经实现了 Sharpe / Calmar / 年化收益 / 最大回撤 / 换手率 / Q5 回测，但 plan 文档里没写：

- [ ] 验收标准里补上：年化 Sharpe、最大回撤、换手率、Q5 回测净值
- [ ] 明确这些指标的计算口径（5 日调仓、等权、单边交易成本默认 0.1%）

### 12. 市场状态分层和因子拥挤度

- [ ] **市值分组 IC**：按 total_mv 分大/中/小票三组，分别报告 IC —— 判断因子容量
- [ ] **行业暴露检查**：中性化后残差在各行业的均值，验证中性化是否彻底（现有 `factor_industry_exposure` 已有，纳入评价流程即可）
- [ ] **牛熊市分层 IC**：按指数 20/60 日均线分牛市/熊市，分别报告 mean IC（可以第二版做，但 plan 保留入口）

### 13. CLI 补充验证命令

- [ ] 除 `list-factors` 和 `evaluate-factor` 外，加 `validate-registry`：
  - 校验 `factor_id` 唯一
  - 必填字段完整
  - 引用的 `data_fields` 是否存在于 `daily_panel`
  - `builtin:*` 实现是否存在
- [ ] 加 `show-result --factor-id X`（第二版也可以）

---

## P3 — 锦上添花

### 14. 预处理参数可配置化

plan 中预处理参数目前散落在代码里。统一进 `configs/evaluation.yaml`：

| 参数 | 配置路径 | 默认值 |
|------|---------|--------|
| Winsorize 方法 | `preprocess.winsorize.method` | mad |
| MAD 倍数 | `preprocess.winsorize.n_mad` | 3.0 |
| 百分位边界 | `preprocess.winsorize.limits` | (0.01, 0.99) |
| 中性化方法 | `preprocess.neutralize` | industry_size |
| 分组数 | `evaluation.n_quantiles` | 5 |
| Primary horizon | `evaluation.primary_horizon` | 5 |

### 15. 分层单调性的统计检验

现有 `_is_monotonic` 只检查 Q1→Q5 均值是否单调。补充：

- [ ] Q5 - Q1 差异的 t 统计量（判断 spread 是否显著不为零）
- [ ] 相邻分组间的 t 检验

### 16. 边界情况处理

plan 需要列出以下边界情况的设计：

- [ ] 某交易日截面股票数 < 30：跳过该日，记录 skipped_dates
- [ ] 因子值全为 NaN：直接 rejected，reason = "calculation yielded all NaN"
- [ ] 因子方差为零（常量因子）：preprocessing 前检测，直接 rejected
- [ ] daily_panel 无数据：CLI 报清晰错误，不 traceback

### 17. 中性化顺序的统计注释

当前流程 `winsorize → zscore → neutralize → re-standardize`。plan 文档应注明：

- [ ] neutralization 发生在 zscore 之后（而非之前），报告中的 factor exposure 数字解释需参考此顺序
- [ ] 这个顺序不影响 IC/RankIC（因为是秩相关系数），但影响回归 beta 的解释

---

## 附：Gate YAML 草案

以下是 `configs/evaluation.yaml` 中 gate 部分的完整草案，供 Codex 直接落进方案文档。

```yaml
gate:
  hard:
    - metric: mean_rank_ic
      operator: ">"
      threshold: 0.0
      reason_on_fail: "IC方向错误或零预测能力"
    - metric: coverage_pct
      operator: ">"
      threshold: 0.3
      reason_on_fail: "因子覆盖率不足，样本偏差严重"
    - metric: n_valid_dates
      operator: ">"
      threshold: 60
      reason_on_fail: "有效交易日过少，统计不可靠"

  soft:
    metrics:
      mean_rank_ic:
        weight: 0.20
        scoring:
          0.00: 0
          0.01: 3
          0.02: 5
          0.03: 7
          0.05: 9
          0.07: 10

      ic_ir:
        weight: 0.20
        scoring:
          0.0: 0
          0.2: 3
          0.3: 5
          0.5: 7
          0.8: 9
          1.0: 10

      win_rate:
        weight: 0.10
        scoring:
          0.48: 0
          0.50: 2
          0.52: 4
          0.55: 6
          0.58: 8
          0.60: 10

      long_short_sharpe:
        weight: 0.15
        scoring:
          0.0: 0
          0.3: 3
          0.5: 5
          0.8: 7
          1.2: 9
          1.5: 10

      mean_turnover:
        weight: 0.10
        scoring:
          0.5: 0
          0.4: 2
          0.3: 4
          0.2: 7
          0.1: 9
          0.05: 10

      is_monotonic:
        weight: 0.10
        scoring:
          false: 0
          true: 10

      pct_abs_t_gt_2:
        weight: 0.10
        scoring:
          0.0: 0
          0.2: 3
          0.3: 5
          0.4: 7
          0.5: 10

      ic_half_life:
        weight: 0.05
        scoring:
          0: 0
          2: 3
          3: 5
          5: 7
          10: 9
          15: 10

    decision:
      active: "score >= 6.5"
      watch: "score >= 4.0"

    category_overrides:
      momentum:
        metrics:
          mean_turnover:
            weight: 0.15
          win_rate:
            weight: 0.08
      reversal:
        metrics:
          win_rate:
            weight: 0.05
          long_short_sharpe:
            weight: 0.20
      volatility:
        metrics:
          is_monotonic:
            weight: 0.05
          ic_half_life:
            weight: 0.10
```

注意：scoring 阈值之间用**线性插值**补全（如 ic_ir=0.4 → 介于 0.3→5 和 0.5→7 → 打 6 分）。category_overrides 只覆盖需要调的字段时间，未列出的指标沿用 defaults。

---

## Gate 决策流程伪代码

```python
def apply_gate(eval_result: EvaluationResult, config: GateConfig) -> GateDecision:
    reasons = []
    
    # --- Hard gate ---
    for rule in config.hard:
        value = get_metric(eval_result, rule.metric)
        if not rule.check(value):
            return GateDecision(
                status="rejected",
                reasons=[f"HARD FAIL: {rule.reason_on_fail} (got {value})"],
                hard_passed=False,
                metric_scores={},
                total_score=None,
            )
    
    # --- Soft gate ---
    category = eval_result.factor_category
    overrides = config.soft.category_overrides.get(category, {})
    scores = {}
    total = 0.0
    
    for metric_name, spec in config.soft.metrics.items():
        override = overrides.get(metric_name, {})
        weight = override.get("weight", spec.weight)
        value = get_metric(eval_result, metric_name)
        score = linear_interpolate(spec.scoring, value)
        scores[metric_name] = score
        total += score * weight
        if score < 3:
            reasons.append(f"{metric_name}偏低 ({score}/10)")
    
    if total >= 6.5:
        status = "active"
    elif total >= 4.0:
        status = "watch"
    else:
        status = "rejected"
    
    return GateDecision(
        status=status,
        reasons=reasons,
        hard_passed=True,
        metric_scores=scores,
        total_score=total,
    )
```

---

## 验收方式

- [x] 方案文档 `docs/plans/2026-06-07-factor-factory-v1-four-module-plan.md` 已更新，涵盖上述所有勾选项目
- [x] Gate YAML 草案已落进 `configs/evaluation.yaml`（如果文件尚不存在，创建模板）
- [x] `FactorSpec` dataclass 已补充 `direction` 字段的注释说明
- [x] sample_builder 相关的过滤逻辑描述已更新
- [x] factor_library 状态管理已和 registry 分离描述
- [x] 文档中没有前后矛盾的地方（比如一边说用 statsmodels 一边实际用 lstsq）

## Codex 最终方案

三次修订后，最终方案和原建议中的 hard/soft 打分 gate 不一致，也不把 6 个分析视角实现成 6 个复杂 gate 模块。保留四模块工程结构和已有评价指标设计，但把 gate 压缩成三层：Validity Gate 判断可评价性，失败为 `invalid`；Research Evidence Gate 合并方向预测力、分层结构和简化交易表现，判断是否有基本研究信号；Library Decision Gate 合并 baseline comparison、simple OOS 和稳定性检查，最终给出 `rejected / watch / active`。指标只是 decision evidence，不是新的架构层级。
