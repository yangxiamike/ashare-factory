# A股 market radar v1 开发

## 任务目标

基于 [2026-06-08-ashare-radar-v1-plan](../../docs/plans/2026-06-08-ashare-radar-v1-plan.md) 落第一版最小闭环：

- 新建 `src/ashare_radar/` 正式包。
- 复用共享 `daily_panel`，不重建数据底座。
- 提供 `daily` / `news` 最小 CLI。
- 提供配置化风格分组、行业聚合、新闻流水线和 markdown 日报。
- 补齐 `tests/ashare_radar/` smoke tests。

## 本次实现口径

- `data_input` 只做 DuckDB 读取、字段校验和覆盖盘点，不做数据修补。
- 市场温度按规则打分，输出 `risk_on / neutral / risk_off`。
- 风格分组使用 `configs/ashare_radar/style_buckets.yaml` 配置化定义。
- 行业强弱按 `daily_panel.sw_l1_name` 聚合个股收益，`return_method=stock_aggregate`。
- 新闻链路只做 mock/manual 输入、清洗、去重、关键词过滤、规则分类和排序。
- 日报输出 markdown 文本，CLI 负责落盘。

## 验证

- `pytest tests/ashare_radar -q`
- `python -m ashare_radar.cli daily --date 2026-05-29 --report-path <repo-root>/ashare-radar-2026-05-29.md`

## Codex 最终方案

待补最终 commit 后更新。
