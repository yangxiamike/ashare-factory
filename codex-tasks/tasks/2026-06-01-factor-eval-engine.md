# 新建 factor_eval 评估引擎 + 02 notebook

状态：待处理

## 要改什么

详见 `docs/plans/run-factor-eval-mom-20d-1-toasty-hickey.md`，完整开发规格。

### 核心目标

把 01 notebook 里的检验逻辑抽到 `src/factor_eval/`，用一个函数 `run_factor_eval()` 完成单因子自动化评估。

### 新建文件
- [ ] `src/factor_eval/__init__.py`
- [ ] `src/factor_eval/runner.py` — `run_factor_eval()` + `EvalResult` dataclass
- [ ] `src/factor_eval/report.py` — 6 个标准化 plot 函数 + 1 个 scorecard 函数
- [ ] `notebooks/02_single_factor_eval.ipynb` — 调用入口，跨 4 个市场对比 mom_20d

### 关键要求
- [ ] `run_factor_eval()` 支持 `universe` 参数（全市场/hs300/csi500/csi1000）
- [ ] 指数成分股过滤要处理 PIT（index_weight 不是每天都有，要 forward-fill）
- [ ] 所有图表函数输入 EvalResult，输出 matplotlib Figure，不依赖全局状态
- [ ] 02 notebook 输出跨市场对比表（最重要的一张表）
- [ ] 和 01 notebook 的 IC、分层收益等关键指标数值一致

### 不做
- 批量多因子、DuckDB 入库、暴露过多参数

## 验收方式

1. `from factor_eval.runner import run_factor_eval` 不报错
2. 四个 universe 分别跑通，IC 值和 01 notebook 一致
3. 6 张图正常显示
4. 02 notebook 从头到尾顺序执行不出错

## Codex 最终方案

与原建议一致：新增 `src/factor_eval/` 引擎、标准图表函数和 `notebooks/02_single_factor_eval.ipynb`，四个 universe 均使用 `index_weight` 最近一次调仓日成分股做 PIT forward-fill 过滤。额外把 `statsmodels` 补进项目依赖声明，因为现有 `factor_utils.py` 顶层运行时已依赖它。
