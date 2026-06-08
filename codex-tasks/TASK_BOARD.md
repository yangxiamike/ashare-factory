# codex-tasks 任务板

这个文件只做总览，方便夏董后期扫一眼看做过哪些任务。具体要求仍然写在各自任务文件里。

## 任务列表

| 状态 | 任务 | 任务文件 | 解决 commit | Codex 最终口径 |
| --- | --- | --- | --- | --- |
| 已解决 | Tushare -> DuckDB 管线 code review | [tasks/2026-05-31-code-review-issues.md](tasks/2026-05-31-code-review-issues.md) | `61e0840` / `f67090f` / `40cb9d0` | 先收高/中优先级主链路问题，分批补齐参数化查询、recent upsert、增量 schema 对齐和 schema 常量收敛；低优先级项不纳入本轮 |
| 已解决 | 删除防御性冗余和死代码 | [tasks/2026-05-31-redundancy-fix.md](tasks/2026-05-31-redundancy-fix.md) | `40cb9d0` | 按原建议删除死代码、重复校验和宽松类型，并把规范同步补进 AGENTS.md |
| 已解决 | 单因子 MVP 数据和逻辑修复 | [tasks/2026-06-01-factor-data-fixes.md](tasks/2026-06-01-factor-data-fixes.md) | `080c025` / `17f436f` | 复权口径切到 adj_close，IPO 过滤放在 notebook 样本口径层，评分卡补成支持反向单调 |
| 已解决 | 01 notebook 改进点 | [tasks/2026-06-01-notebook-01-issues.md](tasks/2026-06-01-notebook-01-issues.md) | `5447159` | 4 个 issue 已全部落地，并统一成可复用的 notebook 因子研究管线 |
| 已解决 | 累积收益重叠复利 bug | [tasks/2026-06-01-cumulative-return-bug.md](tasks/2026-06-01-cumulative-return-bug.md) | `f6a9644` | 统一改为按 5 日调仓步长累计，并同步修正 notebook 图表、回撤和记分卡口径 |
| 已解决 | 新建 factor_eval 评估引擎 + 02 notebook | [tasks/2026-06-01-factor-eval-engine.md](tasks/2026-06-01-factor-eval-engine.md) | `a29d791` | 按原规格抽出 `factor_eval` 引擎和标准图表，02 notebook 使用 PIT forward-fill 指数成分股口径跑四个 universe 对比 |
| 已解决 | 因子工厂 v1 方案文档 review 改进 | [tasks/2026-06-07-factor-factory-plan-review.md](tasks/2026-06-07-factor-factory-plan-review.md) | `9b1e305` / `377f612` / `db77638` | 三次修订 gate 口径：不把 6 个分析视角做成 6 个 gate 模块，压缩为 Validity / Research Evidence / Library Decision 三层。 |
| 已解决 | 因子工厂 v1 四模块实现 | [tasks/2026-06-07-factor-factory-v1-implementation.md](tasks/2026-06-07-factor-factory-v1-implementation.md) | `91e1db4` | 新增 `ashare_factor` 闭环，串起样本、注册、计算、评价、gate、library 和 CLI；成交额阈值按 Tushare 千元单位换算。 |
| 已解决 | 因子工厂 v1 评审修改 | [tasks/2026-06-07-factor-factory-v1-review-fixes.md](tasks/2026-06-07-factor-factory-v1-review-fixes.md) | `2090177` | 去掉手写 YAML 和静态字段表，补齐 DuckDB 因子/评价入库、noise baseline 与 duckdb_path 透传；simple technical baseline 先保留占位。 |
| 已解决 | 数据偏差修复：幸存者偏差 + 上市天数 + 停牌 | [tasks/2026-06-07-survivorship-bias-fixes.md](tasks/2026-06-07-survivorship-bias-fixes.md) | `5133509` / `bd6edf8` | `stock_basic` 改为按 `L/D/P` 全量拉取，`daily_panel` 过滤上市前脏行并对早期行业缺口做首段回填，历史 DQ 清到 `PASS 7 / WARN 0 / FAIL 0`。 |
| 已解决 | A股 market radar v1 开发 | [tasks/2026-06-08-ashare-radar-v1.md](tasks/2026-06-08-ashare-radar-v1.md) | `c543d2d` | 新增 `ashare_radar` 最小闭环，复用 `daily_panel` 跑市场温度、风格/行业排序、新闻流水线、markdown 日报和 CLI，并补齐 smoke tests。 |

## 使用规则

- `TASK_BOARD.md` 放在 `codex-tasks/` 顶层，具体任务文件放在 `codex-tasks/tasks/`。
- 新增任务时，在这里加一行 `待处理`。
- 任务文件名使用 `YYYY-MM-DD-简短主题.md`。
- Codex 解决后，把状态改成 `已解决`，填上 commit，并用一句话记录 Codex 最终采用的修改口径。
- 如果最终方案和任务文件里的建议不同，在对应任务文件末尾补 `Codex 最终方案`，写清楚差异和原因；如果一致，写 `与原建议一致` 即可。
