# codex-tasks 任务板

这个文件只做总览，方便夏董后期扫一眼看做过哪些任务。具体要求仍然写在各自任务文件里。

## 任务列表

| 状态 | 任务 | 任务文件 | 解决 commit | 备注 |
| --- | --- | --- | --- | --- |
| 待处理 | Tushare -> DuckDB 管线 code review | [tasks/2026-05-31-code-review-issues.md](tasks/2026-05-31-code-review-issues.md) |  |  |
| 待处理 | 删除防御性冗余和死代码 | [tasks/2026-05-31-redundancy-fix.md](tasks/2026-05-31-redundancy-fix.md) |  |  |
| 待处理 | 单因子 MVP 数据和逻辑修复 | [tasks/2026-06-01-factor-data-fixes.md](tasks/2026-06-01-factor-data-fixes.md) |  |  |
| 待处理 | 01 notebook 改进点 | [tasks/2026-06-01-notebook-01-issues.md](tasks/2026-06-01-notebook-01-issues.md) |  |  |

## 使用规则

- `TASK_BOARD.md` 放在 `codex-tasks/` 顶层，具体任务文件放在 `codex-tasks/tasks/`。
- 新增任务时，在这里加一行 `待处理`。
- 任务文件名使用 `YYYY-MM-DD-简短主题.md`。
- Codex 解决后，把状态改成 `已解决`，填上 commit。
