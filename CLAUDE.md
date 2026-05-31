# CLAUDE.md

## codex-tasks 留言跟踪

- `codex-tasks/` 是给 Codex 的任务留言区，由夏董负责转告，不需要 Claude / DeepSeek 直接联系 Codex。
- 每个任务用一个 markdown 文件写清楚，文件名尽量用 `YYYY-MM-DD-简短主题.md`。
- 任务文件里保留最小结构即可：
  - `状态：待处理`
  - `要改什么`
  - `验收方式`
- 多个问题用 checklist 写，方便 Codex 改完后直接勾选。
- Codex 完成后会在原任务文件里把状态改成 `已解决`，并补充修改内容、验证方式和 commit。
- 如果任务需要夏董判断，Codex 会在原任务文件里写明卡住原因。
