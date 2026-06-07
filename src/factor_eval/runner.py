"""Legacy reusable single-factor evaluation runner.

New factor research and evaluation flows should use `ashare_factor`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from factor_utils import (
    assign_quantiles,
    build_factor,
    compute_factor_return_t,
    compute_forward_returns,
    compute_ic_decay,
    compute_quantile_returns,
    compute_rank_ic,
    factor_autocorr_multi_lag,
    ic_half_life,
    ic_summary,
    load_daily_panel,
    long_short_spread,
    ls_summary,
    monthly_ic_heatmap,
    neutralize_by_size,
    rebalance_cumulative_returns,
)

INDEX_CODES = {
    "hs300": "000300.SH",
    "csi500": "000905.SH",
    "csi1000": "000852.SH",
}
ALL_MARKET = "全市场"
NEUTRALIZATION = "industry_size"
FORWARD_HORIZONS = (1, 5, 20)
IC_DECAY_MAX_HORIZON = 20
ALL_FORWARD_HORIZONS = tuple(sorted(set(FORWARD_HORIZONS) | set(range(1, 21))))
N_QUANTILES = 5
REBALANCE_STEP = 5
FACTOR_COL = "factor_industry_size_neutral"
SIZE_FACTOR_COL = "factor_size_neutral"
FWD_COL = "fwd_5d"
TRADING_DAYS_PER_YEAR = 252
DEFAULT_MIN_LISTING_DAYS = 250


@dataclass
class EvalResult:
    """Container for one single-factor evaluation result."""

    factor_name: str
    universe: str
    start_date: str
    neutralization: str
    n_stocks: int
    n_dates: int
    n_valid_rows: int
    min_listing_days: int
    factor_window: int
    distribution: pd.DataFrame
    ic_df: pd.DataFrame
    ic_summary: dict
    ic_decay_df: pd.DataFrame
    half_life: int | None
    regression_summary: dict
    monthly_ic: pd.DataFrame
    autocorr_df: pd.DataFrame
    quantile_summary: pd.DataFrame
    quantile_returns_daily: pd.DataFrame
    long_short_df: pd.DataFrame
    long_short_summary: dict
    long_short_sharpe: float
    long_short_calmar: float
    long_short_annual_return: float
    long_short_annual_vol: float
    long_short_max_dd: float
    is_monotonic: bool | None
    turnover_summary: pd.DataFrame
    mean_turnover: float
    yearly_perf: pd.DataFrame
    backtest_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    backtest_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    scorecard: pd.DataFrame = field(default_factory=pd.DataFrame)
    factor_col: str = FACTOR_COL
    df: pd.DataFrame = field(default_factory=pd.DataFrame)


def run_factor_eval(
    factor_name: str,
    factor_func: Callable[..., pd.DataFrame],
    factor_kwargs: dict,
    duckdb_path: Path,
    *,
    universe: str = ALL_MARKET,
    start_date: str = "20240101",
    min_listing_days: int = DEFAULT_MIN_LISTING_DAYS,
    one_way_cost: float = 0.001,
) -> EvalResult:
    """Run the standard single-factor evaluation pipeline.

    Parameters
    ----------
    factor_name: 因子名称，用于报告标题。
    factor_func: 因子构造函数，签名 (df, **kwargs) -> df。
    factor_kwargs: 传给 factor_func 的参数，必须包含 ``col_name``。
    duckdb_path: DuckDB 数据仓库路径。
    universe: 股票池——``"全市场"`` 或 ``"hs300"`` / ``"csi500"`` / ``"csi1000"``。
    start_date: 样本起始日期 (YYYYMMDD)。
    min_listing_days: 剔除上市不足此天数的股票（默认 250 个交易日 ≈ 1 年）。
    one_way_cost: Q5 回测单边交易成本（默认 0.1%）。
    """

    assert universe == ALL_MARKET or universe in INDEX_CODES
    assert "col_name" in factor_kwargs

    factor_window = factor_kwargs.get("window", 20)
    factor_source_col = factor_kwargs["col_name"]

    # ── 加载 & 筛选 ──
    df = load_daily_panel(duckdb_path, start_date=start_date)
    if universe != ALL_MARKET:
        members = _load_index_members(duckdb_path, INDEX_CODES[universe], start_date)
        df = _filter_by_index(df, members)

    factor_call_kwargs = dict(factor_kwargs)
    factor_call_kwargs.setdefault("dropna", False)
    df = factor_func(df, **factor_call_kwargs)
    df = compute_forward_returns(df, horizons=ALL_FORWARD_HORIZONS)

    longest_fwd_col = f"fwd_{max(FORWARD_HORIZONS)}d"
    df["listed_trade_days"] = df.groupby("ts_code").cumcount() + 1
    df["universe"] = (
        df["adj_close"].notna()
        & ~df["is_suspended"]
        & df["total_mv"].notna()
        & df["total_mv"].gt(0)
        & df["listed_trade_days"].ge(min_listing_days)
        & df[factor_source_col].notna()
        & df[longest_fwd_col].notna()
    )

    # ── 因子预处理 ──
    df = build_factor(
        df,
        factor_col=factor_source_col,
        neutralization=NEUTRALIZATION,
        output_col=FACTOR_COL,
    )
    df = neutralize_by_size(df, "factor_zscore", output_col=SIZE_FACTOR_COL)
    df = assign_quantiles(df, FACTOR_COL, n_quantiles=N_QUANTILES)

    research_sample = df[df["universe"]].copy()

    # ── 分布 ──
    distribution = _factor_distribution(research_sample)

    # ── IC ──
    ic_df = compute_rank_ic(research_sample, FACTOR_COL, FWD_COL)
    ic_summ = ic_summary(ic_df)
    ic_decay_df = compute_ic_decay(research_sample, FACTOR_COL, max_lag=IC_DECAY_MAX_HORIZON)
    half_life = ic_half_life(ic_decay_df)

    # ── 回归法 t 检验 ──
    _, regression_summary = compute_factor_return_t(research_sample, FACTOR_COL, FWD_COL)

    # ── 月度 IC 热力图 ──
    monthly_ic = monthly_ic_heatmap(ic_df)

    # ── 因子自相关 ──
    autocorr_df = factor_autocorr_multi_lag(research_sample, FACTOR_COL, max_lag=5)

    # ── 分层收益 ──
    valid_quantile = df[df["universe"] & df["quantile"].notna() & df[FWD_COL].notna()]
    quantile_summary, quantile_returns_daily, q_pivot = compute_quantile_returns(
        valid_quantile, FWD_COL
    )

    # ── 多空 ──
    long_short_df = long_short_spread(q_pivot, step=REBALANCE_STEP)
    long_short_summary = _normalize_long_short_summary(ls_summary(long_short_df))
    ls_sharpe, ls_calmar, ls_annual_ret, ls_annual_vol, ls_max_dd = _compute_long_short_metrics(
        long_short_df
    )
    is_monotonic = _is_monotonic(quantile_summary)

    # ── 换手 ──
    turnover_summary, mean_turnover = _compute_turnover(df)

    # ── 年度业绩 ──
    yearly_perf = _compute_yearly_perf(ic_df, q_pivot)

    # ── Q5 轻量回测 ──
    backtest_df, backtest_summary = _run_q5_backtest(
        df, one_way_cost=one_way_cost
    )

    # ── 评分卡 ──
    scorecard = _build_scorecard(
        factor_name=factor_name,
        universe=universe,
        n_stocks=research_sample["ts_code"].nunique(),
        ic_summ=ic_summ,
        half_life=half_life,
        is_monotonic=is_monotonic,
        long_short_summary=long_short_summary,
        ls_sharpe=ls_sharpe,
        ls_calmar=ls_calmar,
        ls_annual_return=ls_annual_ret,
        ls_max_dd=ls_max_dd,
        mean_turnover=mean_turnover,
        regression_summary=regression_summary,
        backtest_summary=backtest_summary,
        min_listing_days=min_listing_days,
    )

    return EvalResult(
        factor_name=factor_name,
        universe=universe,
        start_date=start_date,
        neutralization=NEUTRALIZATION,
        n_stocks=research_sample["ts_code"].nunique(),
        n_dates=research_sample["trade_date"].nunique(),
        n_valid_rows=len(research_sample),
        min_listing_days=min_listing_days,
        factor_window=factor_window,
        distribution=distribution,
        ic_df=ic_df,
        ic_summary=ic_summ,
        ic_decay_df=ic_decay_df,
        half_life=half_life,
        regression_summary=regression_summary,
        monthly_ic=monthly_ic,
        autocorr_df=autocorr_df,
        quantile_summary=quantile_summary,
        quantile_returns_daily=quantile_returns_daily,
        long_short_df=long_short_df,
        long_short_summary=long_short_summary,
        long_short_sharpe=ls_sharpe,
        long_short_calmar=ls_calmar,
        long_short_annual_return=ls_annual_ret,
        long_short_annual_vol=ls_annual_vol,
        long_short_max_dd=ls_max_dd,
        is_monotonic=is_monotonic,
        turnover_summary=turnover_summary,
        mean_turnover=mean_turnover,
        yearly_perf=yearly_perf,
        backtest_df=backtest_df,
        backtest_summary=backtest_summary,
        scorecard=scorecard,
        factor_col=FACTOR_COL,
        df=df,
    )


# ═══════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════


def _load_index_members(duckdb_path: Path, index_code: str, start_date: str) -> pd.DataFrame:
    con = duckdb.connect(str(duckdb_path), read_only=True)
    sql = """
    SELECT trade_date, con_code AS ts_code
    FROM index_weight
    WHERE index_code = ? AND trade_date >= ?
    ORDER BY trade_date, con_code
    """
    df = con.execute(sql, [index_code, start_date]).fetchdf()
    con.close()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


def _filter_by_index(df: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    rebalance_dates = sorted(members["trade_date"].unique())
    eval_dates = sorted(df["trade_date"].unique())
    member_sets = {
        rebal_date: set(members.loc[members["trade_date"].eq(rebal_date), "ts_code"])
        for rebal_date in rebalance_dates
    }

    filtered_parts = []
    rebal_idx = 0
    current_rebalance = None
    for eval_date in eval_dates:
        while rebal_idx < len(rebalance_dates) and rebalance_dates[rebal_idx] <= eval_date:
            current_rebalance = rebalance_dates[rebal_idx]
            rebal_idx += 1
        if current_rebalance is None:
            continue
        part = df[df["trade_date"].eq(eval_date)]
        filtered_parts.append(part[part["ts_code"].isin(member_sets[current_rebalance])])

    columns = df.columns
    if not filtered_parts:
        return pd.DataFrame(columns=columns)
    return pd.concat(filtered_parts, ignore_index=True)


def _factor_distribution(research_sample: pd.DataFrame) -> pd.DataFrame:
    rows = []
    cols = ["factor_raw", "factor_zscore", SIZE_FACTOR_COL, FACTOR_COL]
    labels = ["Raw", "Z-score", "Size-Neutral", "Industry+Size-Neutral"]
    for col, label in zip(cols, labels):
        v = research_sample[col].dropna()
        rows.append(
            {
                "version": label,
                "count": len(v),
                "mean": v.mean(),
                "std": v.std(),
                "skew": v.skew(),
                "p01": v.quantile(0.01),
                "p99": v.quantile(0.99),
            }
        )
    return pd.DataFrame(rows)


def _is_monotonic(quantile_summary: pd.DataFrame) -> bool | None:
    mean_returns = quantile_summary.set_index("quantile")["mean_return"]
    if mean_returns.is_monotonic_increasing:
        return True
    if mean_returns.is_monotonic_decreasing:
        return False
    return None


def _normalize_long_short_summary(summary: dict) -> dict:
    return {
        "mean_spread": summary["mean"],
        "volatility": summary["std"],
        "win_rate": summary["win_rate"],
        "cum_return": summary["cum_return"],
        "max_drawdown": summary["max_dd"],
    }


def _compute_long_short_metrics(ls_df: pd.DataFrame) -> tuple[float, float, float, float, float]:
    """Compute annualized Sharpe, Calmar, annual return, annual vol, max DD from long-short.

    Uses daily spread for return/vol and the cumulative curve for max drawdown.
    """
    spread = ls_df["spread"].dropna()
    cum = ls_df["cum_spread"]

    if spread.std() <= 0 or len(spread) < 10:
        return np.nan, np.nan, np.nan, np.nan, np.nan

    annual_return = spread.mean() * TRADING_DAYS_PER_YEAR
    annual_vol = spread.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = annual_return / annual_vol if annual_vol > 0 else np.nan

    equity = 1 + cum
    dd = (equity / equity.cummax() - 1).min()
    calmar = annual_return / abs(dd) if dd < 0 else np.nan

    return sharpe, calmar, annual_return, annual_vol, dd


def _compute_turnover(df: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    dates = sorted(df[df["universe"] & df["quantile"].notna()]["trade_date"].unique())
    turnover_rows = []
    for d1, d2 in zip(dates[:-1], dates[1:]):
        prev = df[df["trade_date"].eq(d1) & df["quantile"].notna()]
        curr = df[df["trade_date"].eq(d2) & df["quantile"].notna()]
        for q in range(1, N_QUANTILES + 1):
            p_set = set(prev.loc[prev["quantile"].eq(q), "ts_code"])
            c_set = set(curr.loc[curr["quantile"].eq(q), "ts_code"])
            if c_set:
                turnover_rows.append(
                    {
                        "trade_date": d2,
                        "quantile": q,
                        "turnover": 1 - len(p_set & c_set) / len(c_set),
                    }
                )

    turnover_df = pd.DataFrame(turnover_rows, columns=["trade_date", "quantile", "turnover"])
    summary = turnover_df.groupby("quantile")["turnover"].mean().reset_index(name="avg_turnover")
    return summary, turnover_df["turnover"].mean()


def _compute_yearly_perf(ic_df: pd.DataFrame, q_pivot: pd.DataFrame) -> pd.DataFrame:
    ic_with_year = ic_df.copy()
    ic_with_year["year"] = ic_with_year["trade_date"].dt.year
    q5_daily = q_pivot[5].dropna()

    rows = []
    for year, year_ic in ic_with_year.groupby("year"):
        year_dates = year_ic["trade_date"]
        year_q5 = q5_daily[q5_daily.index.isin(year_dates)]
        rows.append(
            {
                "year": year,
                "n_days": len(year_ic),
                "mean_ic": year_ic["rank_ic"].mean(),
                "mean_return_q5": year_q5.mean(),
                "cum_return_q5": (1 + year_q5).prod() - 1,
                "win_rate": (year_ic["rank_ic"] > 0).mean(),
            }
        )
    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


def _run_q5_backtest(
    df: pd.DataFrame,
    one_way_cost: float = 0.001,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lightweight Q5 long-only research backtest — equal weight, 5-day rebalance."""
    source = df[
        df["universe"]
        & df["quantile"].eq(N_QUANTILES)
        & df[FWD_COL].notna()
    ].copy()
    rebalance_dates = sorted(source["trade_date"].unique())[::REBALANCE_STEP]

    rows = []
    prev_names: set[str] = set()
    for trade_date in rebalance_dates:
        candidates = source[source["trade_date"].eq(trade_date)]
        selected = candidates
        names = set(selected["ts_code"])
        if not names:
            continue

        gross_ew = selected[FWD_COL].mean()
        turnover = 1.0 if not prev_names else 1 - len(prev_names & names) / len(names)
        cost = 2 * turnover * one_way_cost
        rows.append(
            {
                "trade_date": trade_date,
                "n_holdings": len(names),
                "gross_return": gross_ew,
                "turnover": turnover,
                "cost": cost,
                "net_return": gross_ew - cost,
            }
        )
        prev_names = names

    result = pd.DataFrame(rows)
    if result.empty:
        return result, pd.DataFrame()

    result["gross_equity"] = (1 + result["gross_return"]).cumprod()
    result["net_equity"] = (1 + result["net_return"]).cumprod()
    result["drawdown"] = result["net_equity"] / result["net_equity"].cummax() - 1

    # Summary
    n_periods = len(result)
    ret = result["net_return"]
    equity = result["net_equity"]

    periods_per_year = TRADING_DAYS_PER_YEAR / REBALANCE_STEP
    ann_return = equity.iloc[-1] ** (periods_per_year / n_periods) - 1 if n_periods > 0 else np.nan
    ann_vol = ret.std() * np.sqrt(periods_per_year) if n_periods > 1 else np.nan
    sharpe = ann_return / ann_vol if ann_vol and ann_vol > 0 else np.nan
    max_dd = result["drawdown"].min()
    calmar = ann_return / abs(max_dd) if max_dd and max_dd < 0 else np.nan

    summary = pd.DataFrame(
        [
            ["Q5 调仓次数", f"{n_periods}", "-"],
            ["Q5 平均持仓数", f'{result["n_holdings"].mean():.1f}', "-"],
            ["Q5 累计净值 (净)", f"{equity.iloc[-1]:.4f}", "-"],
            ["Q5 年化收益率", f"{ann_return:.4%}", "Pass" if ann_return > 0 else "Weak"],
            ["Q5 年化波动率", f"{ann_vol:.4%}", "-"],
            ["Q5 Sharpe", f"{sharpe:.3f}" if not np.isnan(sharpe) else "nan", "-"],
            ["Q5 Calmar", f"{calmar:.3f}" if not np.isnan(calmar) else "nan", "-"],
            ["Q5 最大回撤", f"{max_dd:.4%}", "-"],
            ["Q5 平均换手率", f'{result["turnover"].mean():.1%}', "-"],
            ["Q5 平均交易成本", f'{result["cost"].mean():.4%}', "-"],
        ],
        columns=["Metric", "Value", "Judgement"],
    )
    return result, summary


def _build_scorecard(
    *,
    factor_name: str,
    universe: str,
    n_stocks: int,
    ic_summ: dict,
    half_life: int | None,
    is_monotonic: bool | None,
    long_short_summary: dict,
    ls_sharpe: float,
    ls_calmar: float,
    ls_annual_return: float,
    ls_max_dd: float,
    mean_turnover: float,
    regression_summary: dict,
    backtest_summary: pd.DataFrame,
    min_listing_days: int,
) -> pd.DataFrame:
    ic_mean = ic_summ["mean_ic"]
    ic_std = ic_summ["std_ic"]
    ic_win = ic_summ["win_rate"]
    ls_mean = long_short_summary["mean_spread"]
    ls_cum = long_short_summary["cum_return"]
    half_life_str = f"{half_life}d" if half_life else f">{IC_DECAY_MAX_HORIZON}d"

    rows = [
        # ── 概览 ──
        ["因子名称", factor_name, "-"],
        ["股票池", universe, "-"],
        ["样本起始", "", "-"],  # placeholder — notebook 可补充
        ["上市剔除 (交易日)", f"{min_listing_days}d", "-"],
        ["样本股票数", f"{n_stocks:,}", "-"],
        ["样本交易日数", f"{ic_summ['n_days']:,}", "-"],
        # ── IC ──
        ["Mean IC", f"{ic_mean:.4f}", "Pass" if ic_mean > 0 else "Weak"],
        ["IC IR", f"{ic_mean / ic_std:.3f}" if ic_std > 0 else "nan", "-"],
        ["IC Win Rate", f"{ic_win:.1%}", "Pass" if ic_win > 0.5 else "Weak"],
        ["IC Half-life", half_life_str, "-"],
        # ── 回归检验 ──
        ["Mean |t|", f"{regression_summary['mean_abs_t']:.2f}", "-"],
        ["|t|>2 占比", f"{regression_summary['pct_abs_t_gt_2']:.1%}", "Pass" if regression_summary["pct_abs_t_gt_2"] > 0.3 else "Weak"],
        # ── 分层 ──
        [
            "Q1→Q5 单调性",
            "Yes" if is_monotonic else ("No" if is_monotonic is False else "Mixed"),
            "Pass" if is_monotonic else "Review",
        ],
        ["Q5-Q1 日均多空收益", f"{ls_mean:.4%}", "Pass" if ls_mean > 0 else "Weak"],
        ["Q5-Q1 累计多空收益", f"{ls_cum:.4%}", "Pass" if ls_cum > 0 else "Weak"],
        # ── 多空综合评价 ──
        ["Q5-Q1 年化收益率", f"{ls_annual_return:.4%}", "-"],
        ["Q5-Q1 最大回撤", f"{ls_max_dd:.4%}", "-"],
        ["Q5-Q1 Sharpe", f"{ls_sharpe:.3f}" if not np.isnan(ls_sharpe) else "nan", "Pass" if ls_sharpe > 0.5 else "Review"],
        ["Q5-Q1 Calmar", f"{ls_calmar:.3f}" if not np.isnan(ls_calmar) else "nan", "-"],
        # ── 换手 ──
        ["Mean Turnover", f"{mean_turnover:.1%}", "-"],
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value", "Judgement"])
