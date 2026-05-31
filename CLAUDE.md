# CLAUDE.md

## codex-tasks 留言跟踪

- `codex-tasks/` 是 Claude / DeepSeek 写给夏董看的任务材料区，由夏董转述给 Codex 执行。
- 每个任务用一个 markdown 文件写清楚，放在 `codex-tasks/tasks/`。
- 任务文件名使用 `YYYY-MM-DD-简短主题.md`。
- 新增任务后，在 `codex-tasks/TASK_BOARD.md` 里加一行 `待处理`，方便夏董总览。
- 任务文件里保留最小结构即可：
  - `状态：待处理`
  - `要改什么`
  - `验收方式`
- 多个问题用 checklist 写，方便 Codex 改完后直接勾选。
- Codex 完成后只更新 `codex-tasks/TASK_BOARD.md`，不需要在任务文件里回留言。
