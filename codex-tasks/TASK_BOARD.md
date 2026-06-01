# codex-tasks 任务板

这个文件只做总览，方便夏董后期扫一眼看做过哪些任务。具体要求仍然写在各自任务文件里。

## 任务列表

| 状态 | 任务 | 任务文件 | 解决 commit | Codex 最终口径 |
| --- | --- | --- | --- | --- |
| 待处理 | Tushare -> DuckDB 管线 code review | [tasks/2026-05-31-code-review-issues.md](tasks/2026-05-31-code-review-issues.md) |  |  |
| 待处理 | 删除防御性冗余和死代码 | [tasks/2026-05-31-redundancy-fix.md](tasks/2026-05-31-redundancy-fix.md) |  |  |
| 待处理 | 单因子 MVP 数据和逻辑修复 | [tasks/2026-06-01-factor-data-fixes.md](tasks/2026-06-01-factor-data-fixes.md) |  |  |
| 已解决 | 01 notebook 改进点 | [tasks/2026-06-01-notebook-01-issues.md](tasks/2026-06-01-notebook-01-issues.md) | — | 4 个 issue 已全部落地 |
| 已解决 | 累积收益重叠复利 bug | [tasks/2026-06-01-cumulative-return-bug.md](tasks/2026-06-01-cumulative-return-bug.md) | `f6a9644` | 统一改为按 5 日调仓步长累计，并同步修正 notebook 图表、回撤和记分卡口径 |

## 使用规则

- `TASK_BOARD.md` 放在 `codex-tasks/` 顶层，具体任务文件放在 `codex-tasks/tasks/`。
- 新增任务时，在这里加一行 `待处理`。
- 任务文件名使用 `YYYY-MM-DD-简短主题.md`。
- Codex 解决后，把状态改成 `已解决`，填上 commit，并用一句话记录 Codex 最终采用的修改口径。
- 如果最终方案和任务文件里的建议不同，在对应任务文件末尾补 `Codex 最终方案`，写清楚差异和原因；如果一致，写 `与原建议一致` 即可。
