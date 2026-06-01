# 短线因子候选库 + 注册表 v1

## Summary

目标是把现在的 01/02 单因子研究，升级成一条可批量跑的短线因子筛选线。

第一版只服务真实可交易范围：

- 股票池：沪深主板，使用 `stock_basic.market == "主板"`。
- 排除：北交所、科创板、创业板、停牌、上市不足 250 个交易日、关键价格或市值缺失。
- 周期：3-5 日短线波段，沿用当前 `fwd_5d` 和 5 日调仓作为主评估口径。
- 目标：先筛因子，不直接做最终交易系统。

## Key Changes

- 新增短线因子候选库：
  - 价格类：1/3/5 日反转，5/10/20 日动量。
  - 波动类：10/20 日波动率，振幅类因子。
  - 量价类：成交额、换手率、量比、成交额变化。
  - 估值/规模辅助类：市值、PB/PE 等只作为对照或中性化检查，不作为首批主力信号。
- 新增因子注册表：
  - 每个因子统一记录 `name`、中文说明、计算函数、参数、方向、类别、窗口、依赖字段。
  - 注册表是唯一入口，02 notebook 和批量 runner 都从注册表取因子，避免散落函数。
- 改造评估入口：
  - 让 `factor_eval.run_factor_eval` 可以接受注册表里的 `FactorSpec`。
  - 增加 `main_board` universe。
  - 保留现有 `全市场 / hs300 / csi500 / csi1000` 口径，不破坏已有 notebook。
- 新增批量评估脚本或 notebook：
  - 批量跑所有注册因子。
  - 输出一张总评分表：Mean IC、IC Win Rate、Q5-Q1、Q5 回测年化、回撤、换手、样本股票数。
  - 按主板股票池排序，找出值得进入下一轮交易化验证的因子。

## Public Interfaces

- 新增 `FactorSpec`：
  - `name`
  - `display_name`
  - `category`
  - `func`
  - `kwargs`
  - `direction`
  - `required_columns`
  - `description`
- 新增注册表访问：
  - `get_factor(name)`
  - `iter_factors(category=None)`
- 扩展评估 universe：
  - 新增 `"main_board"`，含义固定为沪深主板。
- 批量结果字段固定：
  - `factor_name`
  - `display_name`
  - `category`
  - `universe`
  - `mean_ic`
  - `ic_ir`
  - `ic_win_rate`
  - `q5_q1_mean_spread`
  - `q5_q1_cum_return`
  - `q5_annual_return`
  - `q5_max_drawdown`
  - `mean_turnover`
  - `n_stocks`
  - `n_dates`

## Test Plan

- 单元测试：
  - 注册表能列出全部因子，且每个因子都有唯一 `name`。
  - 每个因子的 `required_columns` 都存在于 `daily_panel` 可加载字段中。
  - `main_board` universe 只保留 `market == "主板"`。
  - 原有 `mom_20d` 评估结果仍能跑通。
- 集成测试：
  - 批量跑 2-3 个轻量因子，确认输出评分表字段完整。
  - 对 `main_board` 跑 `mom_20d`，确认不包含创业板、科创板、北交所。
- 人工验收：
  - 打开批量评分结果，能一眼看出哪些因子值得继续。
  - 02 notebook 原流程不被破坏。

## Assumptions

- 第一版不用分钟线、盘口、实时成交数据，只使用现有日频数据。
- 第一版不直接生成买卖指令，只生成因子优先级和可继续研究名单。
- 主评估标签用 `fwd_5d`，辅助观察 `fwd_1d` 和 `fwd_20d`。
- 调仓成本沿用当前默认单边 `0.1%`。
- 本任务实施完成后按仓库要求单独 commit。
