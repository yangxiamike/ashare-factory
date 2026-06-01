"""Reusable single-factor evaluation runner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from factor_utils import (
    assign_quantiles,
    build_factor,
    compute_forward_returns,
    compute_ic_decay,
    compute_quantile_returns,
    compute_rank_ic,
    ic_half_life,
    ic_summary,
    load_daily_panel,
    long_short_spread,
    ls_summary,
    neutralize_by_size,
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


@dataclass(frozen=True)
class EvalResult:
    """Container for one single-factor evaluation result."""

    factor_name: str
    universe: str
    start_date: str
    neutralization: str
    n_stocks: int
    n_dates: int
    n_valid_rows: int
    distribution: pd.DataFrame
    ic_df: pd.DataFrame
    ic_summary: dict
    ic_decay_df: pd.DataFrame
    half_life: int | None
    quantile_summary: pd.DataFrame
    quantile_returns_daily: pd.DataFrame
    long_short_df: pd.DataFrame
    long_short_summary: dict
    is_monotonic: bool | None
    turnover_summary: pd.DataFrame
    mean_turnover: float
    yearly_perf: pd.DataFrame
    scorecard: pd.DataFrame
    factor_col: str
    df: pd.DataFrame


def run_factor_eval(
    factor_name: str,
    factor_func: Callable[..., pd.DataFrame],
    factor_kwargs: dict,
    duckdb_path: Path,
    *,
    universe: str = ALL_MARKET,
    start_date: str = "20240101",
) -> EvalResult:
    """Run the standard single-factor evaluation pipeline."""

    assert universe == ALL_MARKET or universe in INDEX_CODES
    assert "col_name" in factor_kwargs

    df = load_daily_panel(duckdb_path, start_date=start_date)
    if universe != ALL_MARKET:
        members = _load_index_members(duckdb_path, INDEX_CODES[universe], start_date)
        df = _filter_by_index(df, members)

    factor_call_kwargs = dict(factor_kwargs)
    factor_call_kwargs.setdefault("dropna", False)
    df = factor_func(df, **factor_call_kwargs)
    df = compute_forward_returns(df, horizons=ALL_FORWARD_HORIZONS)

    factor_window = factor_kwargs.get("window", 20)
    min_listing_days = factor_window + max(FORWARD_HORIZONS) + 1
    factor_source_col = factor_kwargs["col_name"]
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

    df = build_factor(
        df,
        factor_col=factor_source_col,
        neutralization=NEUTRALIZATION,
        output_col=FACTOR_COL,
    )
    df = neutralize_by_size(df, "factor_zscore", output_col=SIZE_FACTOR_COL)
    df = assign_quantiles(df, FACTOR_COL, n_quantiles=N_QUANTILES)

    research_sample = df[df["universe"]].copy()
    distribution = _factor_distribution(research_sample)
    ic_df = compute_rank_ic(research_sample, FACTOR_COL, FWD_COL)
    ic_summ = ic_summary(ic_df)
    ic_decay_df = compute_ic_decay(research_sample, FACTOR_COL, max_lag=IC_DECAY_MAX_HORIZON)
    half_life = ic_half_life(ic_decay_df)

    valid_quantile = df[df["universe"] & df["quantile"].notna() & df[FWD_COL].notna()]
    quantile_summary, quantile_returns_daily, q_pivot = compute_quantile_returns(
        valid_quantile,
        FWD_COL,
    )
    long_short_df = long_short_spread(q_pivot, step=REBALANCE_STEP)
    long_short_summary = _normalize_long_short_summary(ls_summary(long_short_df))
    is_monotonic = _is_monotonic(quantile_summary)
    turnover_summary, mean_turnover = _compute_turnover(df)
    yearly_perf = _compute_yearly_perf(ic_df, q_pivot)
    scorecard = _build_scorecard(
        factor_name=factor_name,
        universe=universe,
        n_stocks=research_sample["ts_code"].nunique(),
        ic_summ=ic_summ,
        half_life=half_life,
        is_monotonic=is_monotonic,
        long_short_summary=long_short_summary,
        mean_turnover=mean_turnover,
    )

    return EvalResult(
        factor_name=factor_name,
        universe=universe,
        start_date=start_date,
        neutralization=NEUTRALIZATION,
        n_stocks=research_sample["ts_code"].nunique(),
        n_dates=research_sample["trade_date"].nunique(),
        n_valid_rows=len(research_sample),
        distribution=distribution,
        ic_df=ic_df,
        ic_summary=ic_summ,
        ic_decay_df=ic_decay_df,
        half_life=half_life,
        quantile_summary=quantile_summary,
        quantile_returns_daily=quantile_returns_daily,
        long_short_df=long_short_df,
        long_short_summary=long_short_summary,
        is_monotonic=is_monotonic,
        turnover_summary=turnover_summary,
        mean_turnover=mean_turnover,
        yearly_perf=yearly_perf,
        scorecard=scorecard,
        factor_col=FACTOR_COL,
        df=df,
    )


def _load_index_members(duckdb_path: Path, index_code: str, start_date: str) -> pd.DataFrame:
    """Load rebalance-date index constituents from DuckDB."""

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
    """Filter rows with point-in-time index membership using forward-filled rebalances."""

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
    summary = (
        turnover_df.groupby("quantile")["turnover"].mean().reset_index(name="avg_turnover")
    )
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


def _build_scorecard(
    *,
    factor_name: str,
    universe: str,
    n_stocks: int,
    ic_summ: dict,
    half_life: int | None,
    is_monotonic: bool | None,
    long_short_summary: dict,
    mean_turnover: float,
) -> pd.DataFrame:
    ic_mean = ic_summ["mean_ic"]
    ic_std = ic_summ["std_ic"]
    ic_win = ic_summ["win_rate"]
    ls_mean = long_short_summary["mean_spread"]
    ls_cum = long_short_summary["cum_return"]

    return pd.DataFrame(
        [
            ["Factor", factor_name, "-"],
            ["Universe", universe, "-"],
            ["N stocks", f"{n_stocks:,}", "-"],
            ["N dates", f"{ic_summ['n_days']:,}", "-"],
            ["Mean IC", f"{ic_mean:.4f}", "Pass" if ic_mean > 0 else "Weak"],
            ["IC IR", f"{ic_mean / ic_std:.3f}" if ic_std > 0 else "nan", "-"],
            ["IC Win Rate", f"{ic_win:.1%}", "Pass" if ic_win > 0.5 else "Weak"],
            ["IC Half-life", f"{half_life}d" if half_life else f">{IC_DECAY_MAX_HORIZON}d", "-"],
            [
                "Q1→Q5 Monotonic",
                "Yes" if is_monotonic else ("No" if is_monotonic is False else "Mixed"),
                "Pass" if is_monotonic else "Review",
            ],
            ["Q5-Q1 Mean Spread", f"{ls_mean:.4%}", "Pass" if ls_mean > 0 else "Weak"],
            ["Q5-Q1 Cum Return", f"{ls_cum:.4%}", "Pass" if ls_cum > 0 else "Weak"],
            ["Mean Turnover", f"{mean_turnover:.1%}", "-"],
        ],
        columns=["Metric", "Value", "Judgement"],
    )
