from __future__ import annotations

from dataclasses import asdict, is_dataclass
from math import sqrt
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def assign_quantiles(df: pd.DataFrame, factor_col: str, n_quantiles: int = 5) -> pd.DataFrame:
    """Assign quantile groups (1..n_quantiles) per date."""
    result = df.copy()
    result["quantile"] = pd.NA
    for _, group in result.groupby("trade_date"):
        mask = group[factor_col].notna()
        if mask.sum() < n_quantiles:
            continue
        result.loc[group.index[mask], "quantile"] = pd.qcut(
            group.loc[mask, factor_col].rank(method="first"),
            q=n_quantiles,
            labels=list(range(1, n_quantiles + 1)),
        ).astype(int)
    result["quantile"] = result["quantile"].astype("Int64")
    return result


def compute_rank_ic(df: pd.DataFrame, factor_col: str, forward_col: str) -> pd.DataFrame:
    """Compute daily rank IC between factor and forward return."""
    records: list[dict[str, Any]] = []
    for trade_date, group in df.groupby("trade_date"):
        valid = group[[factor_col, forward_col]].dropna()
        if len(valid) < 10:
            continue
        records.append(
            {
                "trade_date": trade_date,
                "rank_ic": valid[factor_col].rank().corr(valid[forward_col].rank()),
                "n_stocks": len(valid),
            }
        )
    columns = ["trade_date", "rank_ic", "n_stocks"]
    return pd.DataFrame(records, columns=columns).sort_values("trade_date").reset_index(drop=True)


def compute_quantile_returns(df: pd.DataFrame, forward_col: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute mean forward return by quantile per date."""
    daily = (
        df.dropna(subset=["quantile", forward_col])
        .groupby(["trade_date", "quantile"])[forward_col]
        .mean()
        .reset_index()
        .rename(columns={forward_col: "avg_return"})
    )
    summary = (
        daily.groupby("quantile")["avg_return"]
        .agg(["mean", "std", "count"])
        .rename(columns={"mean": "mean_return", "std": "std_return"})
        .reset_index()
    )
    summary["hit_rate"] = daily.groupby("quantile")["avg_return"].apply(lambda s: (s > 0).mean()).values
    pivot = daily.pivot(index="trade_date", columns="quantile", values="avg_return").sort_index()
    return summary, daily, pivot


def _rebalance_cumulative_returns(returns: pd.Series, *, step: int = 5) -> pd.Series:
    """Compound overlapping forward returns only on rebalance observations."""
    assert step >= 1
    sampled = returns.fillna(0).iloc[::step]
    cumulative = (1 + sampled).cumprod() - 1
    return cumulative.reindex(returns.index).ffill()


def long_short_spread(pivot: pd.DataFrame, step: int = 5) -> pd.DataFrame:
    """Compute Q5-Q1 long-short spread from quantile pivot."""
    result = pd.DataFrame(
        {
            "trade_date": pivot.index,
            "spread": pivot.get(5, 0) - pivot.get(1, 0),
        }
    )
    result["cum_spread"] = _rebalance_cumulative_returns(result["spread"], step=step).to_numpy()
    return result


def factor_autocorr_multi_lag(df: pd.DataFrame, factor_col: str, max_lag: int = 5) -> pd.DataFrame:
    """Compute factor rank autocorrelation at lags 1..max_lag."""
    dates = sorted(df["trade_date"].unique())
    lag_results: list[dict[str, Any]] = []
    for lag in range(1, max_lag + 1):
        values: list[float] = []
        for index in range(lag, len(dates)):
            prev_date = dates[index - lag]
            curr_date = dates[index]
            prev = df.loc[df["trade_date"].eq(prev_date), ["ts_code", factor_col]].rename(columns={factor_col: "f_prev"})
            curr = df.loc[df["trade_date"].eq(curr_date), ["ts_code", factor_col]].rename(columns={factor_col: "f_curr"})
            merged = prev.merge(curr, on="ts_code")
            if len(merged) < 10:
                continue
            values.append(merged["f_prev"].rank().corr(merged["f_curr"].rank()))
        lag_results.append({"lag": lag, "mean_autocorr": np.mean(values) if values else np.nan})
    return pd.DataFrame(lag_results)


def factor_industry_exposure(
    df: pd.DataFrame,
    factor_col: str,
    industry_col: str = "sw_l1_name",
) -> pd.DataFrame:
    """Compute mean and standardized factor exposure per industry."""
    valid = df[[factor_col, industry_col]].dropna()
    grouped = valid.groupby(industry_col)
    result = pd.DataFrame(
        {
            "industry": grouped[factor_col].mean().index,
            "mean_exposure": grouped[factor_col].mean().values,
            "std_exposure": grouped[factor_col].std(ddof=0).values,
            "n_stocks": grouped.size().values,
        }
    )
    std = result["std_exposure"]
    result["normalized_exposure"] = np.where(std > 0, result["mean_exposure"] / std, 0.0)
    return result.sort_values("mean_exposure", ascending=False).reset_index(drop=True)


def to_plain_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {k: to_plain_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_plain_dict(v) for v in value]
    return value


def frame_to_records(frame: pd.DataFrame, *, date_format: str = "%Y-%m-%d", limit: int | None = None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    if limit is not None:
        frame = frame.head(limit)
    result = frame.copy()
    for column in result.columns:
        if pd.api.types.is_datetime64_any_dtype(result[column]):
            result[column] = result[column].dt.strftime(date_format)
    return sanitize_for_json(result.to_dict(orient="records"))


def sanitize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_json(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize_for_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        if pd.isna(value) or np.isinf(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if value is pd.NA:
        return None
    return value


def compute_evaluation_metrics(
    factor_df: pd.DataFrame,
    *,
    factor_col: str,
    direction_col: str,
    forward_col: str,
    raw_factor_col: str | None = None,
    n_quantiles: int = 5,
    rebalance_days: int = 5,
    rolling_ic_window: int = 252,
    min_cross_section_count: int = 30,
) -> dict[str, Any]:
    frame = factor_df.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    total_rows = len(frame)
    factor_source_col = raw_factor_col or factor_col
    valid_mask = frame[direction_col].notna() & frame[forward_col].notna()
    coverage_pct = float(valid_mask.mean()) if total_rows else 0.0

    daily_counts = (
        frame.loc[valid_mask]
        .groupby("trade_date")
        .size()
        .rename("n_valid")
        .reset_index()
    )
    skipped_dates = (
        daily_counts.loc[daily_counts["n_valid"] < min_cross_section_count, "trade_date"]
        .dt.strftime("%Y-%m-%d")
        .tolist()
    )

    usable = frame.loc[valid_mask].copy()
    usable = usable.groupby("trade_date").filter(lambda g: len(g) >= min_cross_section_count)
    if usable.empty:
        return {
            "coverage_pct": coverage_pct,
            "n_total_rows": total_rows,
            "n_forward_return_samples": int(valid_mask.sum()),
            "n_valid_rows": 0,
            "n_valid_dates": 0,
            "skipped_dates": skipped_dates,
            "ic": {},
            "rank_ic": {},
            "quantile": {},
            "long_short": {},
            "top_quantile": {},
            "turnover": {},
            "stability": {},
            "size_bucket_rank_ic": {},
            "industry_exposure": [],
            "yearly": [],
            "market_regime_rank_ic": {},
        }

    raw_valid = frame[factor_source_col].dropna()
    processed_valid = frame[factor_col].dropna()
    usable = assign_quantiles(usable, direction_col, n_quantiles=n_quantiles)

    rank_ic_df = compute_rank_ic(usable, direction_col, forward_col)
    pearson_ic_df = _compute_daily_ic(usable, direction_col, forward_col, method="pearson")

    quantile_summary, quantile_daily, quantile_pivot = compute_quantile_returns(usable, forward_col)
    long_short_df = long_short_spread(quantile_pivot, step=rebalance_days)
    top_backtest = _compute_top_quantile_backtest(
        usable,
        forward_col=forward_col,
        quantile_col="quantile",
        top_quantile=n_quantiles,
        rebalance_days=rebalance_days,
    )
    turnover = _compute_turnover(usable, quantile_col="quantile")

    metrics = {
        "coverage_pct": coverage_pct,
        "n_total_rows": total_rows,
        "n_forward_return_samples": int(valid_mask.sum()),
        "n_valid_rows": int(len(usable)),
        "n_valid_dates": int(usable["trade_date"].nunique()),
        "skipped_dates": skipped_dates,
        "distribution": {
            "raw": _distribution_summary(raw_valid),
            "processed": _distribution_summary(processed_valid),
        },
        "ic": _ic_stats(pearson_ic_df["ic"] if not pearson_ic_df.empty else pd.Series(dtype=float), rolling_window=rolling_ic_window),
        "rank_ic": _ic_stats(rank_ic_df["rank_ic"] if not rank_ic_df.empty else pd.Series(dtype=float), rolling_window=rolling_ic_window),
        "quantile": _quantile_metrics(quantile_summary, quantile_daily, top_quantile=n_quantiles),
        "long_short": _long_short_metrics(long_short_df, rebalance_days=rebalance_days),
        "top_quantile": _top_quantile_metrics(top_backtest),
        "turnover": turnover,
        "stability": _stability_metrics(
            rank_ic_df=rank_ic_df,
            autocorr_df=factor_autocorr_multi_lag(usable, direction_col, max_lag=5),
            long_short_df=long_short_df,
            yearly=_yearly_metrics(rank_ic_df, quantile_daily, top_quantile=n_quantiles),
        ),
        "size_bucket_rank_ic": _size_bucket_rank_ic(usable, direction_col, forward_col),
        "industry_exposure": frame_to_records(
            factor_industry_exposure(usable, factor_col).head(10)
            if "sw_l1_name" in usable.columns
            else pd.DataFrame()
        ),
        "yearly": _yearly_metrics(rank_ic_df, quantile_daily, top_quantile=n_quantiles),
        "market_regime_rank_ic": {
            "enabled": False,
            "status": "placeholder",
            "reason": "market regime split reserved for later version",
        },
        "artifacts": {
            "rank_ic_daily": frame_to_records(rank_ic_df),
            "ic_daily": frame_to_records(pearson_ic_df),
            "quantile_summary": frame_to_records(quantile_summary),
            "quantile_daily": frame_to_records(quantile_daily, limit=200),
            "long_short_daily": frame_to_records(long_short_df),
            "top_quantile_backtest": frame_to_records(top_backtest),
        },
    }

    metrics["quantile"]["monotonicity"] = _monotonicity_flag(quantile_summary)
    return sanitize_for_json(metrics)


def compare_with_baselines(
    candidate_result: dict[str, Any],
    baseline_input: dict[str, Any] | None,
    baseline_config: dict[str, Any] | None,
) -> dict[str, Any]:
    if not baseline_input:
        groups = {}
        evidence_cfg = ((baseline_config or {}).get("evidence") or {}).get("baseline_comparison", {})
        for group_name, baseline_names in evidence_cfg.items():
            if isinstance(baseline_names, dict) and not baseline_names.get("enabled", True):
                continue
            if isinstance(baseline_names, dict):
                baseline_names = baseline_names.get("items", [])
            groups[group_name] = {
                "status": "placeholder",
                "baselines": list(baseline_names),
                "reason": "baseline results not provided in this run",
            }
        return {"status": "placeholder", "groups": groups}

    groups = {}
    candidate_metrics = _candidate_comparison_vector(candidate_result)
    for group_name, entries in baseline_input.items():
        rows = [entry for entry in entries if isinstance(entry, dict)]
        if not rows:
            groups[group_name] = {"status": "placeholder", "reason": "no comparable baseline rows"}
            continue
        group_metrics = {}
        for metric_name, candidate_value in candidate_metrics.items():
            values = [row.get(metric_name) for row in rows if row.get(metric_name) is not None]
            if candidate_value is None or not values:
                continue
            higher_is_better = metric_name not in {"max_drawdown", "mean_turnover"}
            score = _percentile_rank(candidate_value, values, higher_is_better=higher_is_better)
            group_metrics[metric_name] = {
                "candidate": candidate_value,
                "baseline_median": float(np.median(values)),
                "percentile": score,
            }
        groups[group_name] = {
            "status": "ok",
            "n_baselines": len(rows),
            "metrics": group_metrics,
        }

    noise_rank = groups.get("noise", {}).get("metrics", {}).get("rank_ic_mean", {}).get("percentile")
    simple_rank = groups.get("simple_technical", {}).get("metrics", {}).get("rank_ic_mean", {}).get("percentile")
    return sanitize_for_json(
        {
            "status": "ok",
            "groups": groups,
            "summary": {
                "stronger_than_most_noise_baselines": noise_rank is not None and noise_rank >= 0.5,
                "not_worse_than_simple_technical_baselines": simple_rank is not None and simple_rank >= 0.3,
            },
        }
    )


def _candidate_comparison_vector(result: dict[str, Any]) -> dict[str, float | None]:
    full_sample = result["metrics"]["full_sample"]
    oos = result.get("oos_evidence", {}).get("out_of_sample", {})
    return {
        "rank_ic_mean": full_sample.get("rank_ic", {}).get("mean"),
        "top_quantile_return": full_sample.get("top_quantile", {}).get("mean_return"),
        "top_quantile_sharpe": full_sample.get("top_quantile", {}).get("sharpe"),
        "max_drawdown": full_sample.get("top_quantile", {}).get("max_drawdown"),
        "mean_turnover": full_sample.get("turnover", {}).get("mean_turnover"),
        "oos_rank_ic_mean": oos.get("rank_ic", {}).get("mean"),
    }


def _distribution_summary(series: pd.Series) -> dict[str, Any]:
    if series.empty:
        return {}
    return sanitize_for_json(
        {
            "count": len(series),
            "mean": series.mean(),
            "std": series.std(ddof=0),
            "skew": series.skew(),
            "kurtosis": series.kurtosis(),
            "p01": series.quantile(0.01),
            "p50": series.quantile(0.50),
            "p99": series.quantile(0.99),
        }
    )


def _compute_daily_ic(frame: pd.DataFrame, factor_col: str, forward_col: str, *, method: str) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for trade_date, group in frame.groupby("trade_date"):
        valid = group[[factor_col, forward_col]].dropna()
        if len(valid) < 10:
            continue
        if method == "pearson":
            ic_value = valid[factor_col].corr(valid[forward_col])
        else:
            ic_value = valid[factor_col].rank().corr(valid[forward_col].rank())
        records.append({"trade_date": trade_date, "ic": ic_value, "n_stocks": len(valid)})
    return pd.DataFrame(records).sort_values("trade_date").reset_index(drop=True)


def _ic_stats(series: pd.Series, *, rolling_window: int) -> dict[str, Any]:
    clean = pd.Series(series).dropna()
    if clean.empty:
        return {}
    std = clean.std(ddof=0)
    mean = clean.mean()
    rolling = clean.rolling(rolling_window, min_periods=min(20, rolling_window)).mean()
    return sanitize_for_json(
        {
            "mean": mean,
            "std": std,
            "ir": mean / std if std > 0 else np.nan,
            "t_stat": mean / (std / sqrt(len(clean))) if std > 0 else np.nan,
            "win_rate": (clean > 0).mean(),
            "positive_pct": (clean > 0).mean(),
            "negative_pct": (clean < 0).mean(),
            "extreme_negative_pct": (clean < (-1.0 * std)).mean() if std > 0 else np.nan,
            "skew": clean.skew(),
            "kurtosis": clean.kurtosis(),
            "n_days": len(clean),
            "rolling_mean_tail": rolling.dropna().tail(5).tolist(),
            "rolling_mean_latest": rolling.dropna().iloc[-1] if not rolling.dropna().empty else np.nan,
        }
    )


def _quantile_metrics(quantile_summary: pd.DataFrame, quantile_daily: pd.DataFrame, *, top_quantile: int) -> dict[str, Any]:
    if quantile_summary.empty:
        return {}
    spread_daily = quantile_daily.pivot(index="trade_date", columns="quantile", values="avg_return")
    spread = spread_daily.get(top_quantile, pd.Series(dtype=float)) - spread_daily.get(1, pd.Series(dtype=float))
    spread = spread.dropna()
    return sanitize_for_json(
        {
            "summary": frame_to_records(quantile_summary),
            "q5_q1_spread_mean": spread.mean() if not spread.empty else np.nan,
            "q5_q1_spread_t_stat": _series_t_stat(spread),
            "adjacent_spread_t_stats": _adjacent_t_stats(spread_daily),
        }
    )


def _top_quantile_metrics(backtest_df: pd.DataFrame) -> dict[str, Any]:
    if backtest_df.empty:
        return {}
    ret = backtest_df["net_return"].dropna()
    ann_return, ann_vol, sharpe, calmar, max_dd = _annualized_metrics(ret, backtest_df["net_equity"])
    return sanitize_for_json(
        {
            "mean_return": ret.mean(),
            "annual_return": ann_return,
            "annual_volatility": ann_vol,
            "sharpe": sharpe,
            "calmar": calmar,
            "max_drawdown": max_dd,
            "cum_return": backtest_df["net_equity"].iloc[-1] - 1,
            "win_rate": (ret > 0).mean(),
            "mean_turnover": backtest_df["turnover"].mean(),
            "n_rebalances": len(backtest_df),
        }
    )


def _long_short_metrics(long_short_df: pd.DataFrame, *, rebalance_days: int) -> dict[str, Any]:
    if long_short_df.empty:
        return {}
    ret = long_short_df["spread"].dropna()
    ann_return, ann_vol, sharpe, calmar, max_dd = _annualized_metrics(ret, 1 + long_short_df["cum_spread"])
    return sanitize_for_json(
        {
            "mean_return": ret.mean(),
            "annual_return": ann_return,
            "annual_volatility": ann_vol,
            "sharpe": sharpe,
            "calmar": calmar,
            "max_drawdown": max_dd,
            "cum_return": long_short_df["cum_spread"].iloc[-1],
            "win_rate": (ret > 0).mean(),
            "rebalance_days": rebalance_days,
        }
    )


def _compute_top_quantile_backtest(
    frame: pd.DataFrame,
    *,
    forward_col: str,
    quantile_col: str,
    top_quantile: int,
    rebalance_days: int,
) -> pd.DataFrame:
    source = frame.loc[frame[quantile_col].eq(top_quantile) & frame[forward_col].notna()].copy()
    rebalance_dates = sorted(source["trade_date"].unique())[::rebalance_days]
    rows: list[dict[str, Any]] = []
    previous_names: set[str] = set()
    for trade_date in rebalance_dates:
        current = source.loc[source["trade_date"].eq(trade_date)]
        current_names = set(current["ts_code"])
        if not current_names:
            continue
        turnover = 1.0 if not previous_names else 1.0 - len(previous_names & current_names) / len(current_names)
        rows.append(
            {
                "trade_date": trade_date,
                "n_holdings": len(current_names),
                "net_return": current[forward_col].mean(),
                "turnover": turnover,
            }
        )
        previous_names = current_names
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["net_equity"] = (1.0 + result["net_return"]).cumprod()
    result["drawdown"] = result["net_equity"] / result["net_equity"].cummax() - 1.0
    return result


def _compute_turnover(frame: pd.DataFrame, *, quantile_col: str) -> dict[str, Any]:
    dates = sorted(frame.loc[frame[quantile_col].notna(), "trade_date"].unique())
    rows: list[dict[str, Any]] = []
    quantiles = sorted(frame[quantile_col].dropna().astype(int).unique().tolist())
    for prev_date, curr_date in zip(dates[:-1], dates[1:]):
        prev = frame.loc[frame["trade_date"].eq(prev_date)]
        curr = frame.loc[frame["trade_date"].eq(curr_date)]
        for quantile in quantiles:
            prev_names = set(prev.loc[prev[quantile_col].eq(quantile), "ts_code"])
            curr_names = set(curr.loc[curr[quantile_col].eq(quantile), "ts_code"])
            if not curr_names:
                continue
            rows.append(
                {
                    "trade_date": curr_date,
                    "quantile": quantile,
                    "turnover": 1.0 - len(prev_names & curr_names) / len(curr_names),
                }
            )
    turnover_df = pd.DataFrame(rows)
    if turnover_df.empty:
        return {}
    by_quantile = turnover_df.groupby("quantile")["turnover"].mean().to_dict()
    return sanitize_for_json(
        {
            "mean_turnover": turnover_df["turnover"].mean(),
            "turnover_std": turnover_df["turnover"].std(ddof=0),
            "by_quantile": {str(k): v for k, v in by_quantile.items()},
        }
    )


def _stability_metrics(
    *,
    rank_ic_df: pd.DataFrame,
    autocorr_df: pd.DataFrame,
    long_short_df: pd.DataFrame,
    yearly: list[dict[str, Any]],
) -> dict[str, Any]:
    result = {
        "autocorr_decay": frame_to_records(autocorr_df),
        "ic_half_life_lag": _ic_half_life_from_autocorr(autocorr_df),
        "yearly": yearly,
        "single_year_concentration": _single_year_concentration(yearly),
    }
    if not long_short_df.empty:
        result["long_short_negative_streak_max"] = _max_negative_streak(long_short_df["spread"])
    if not rank_ic_df.empty:
        ic_series = rank_ic_df["rank_ic"].dropna()
        result["rank_ic_negative_streak_max"] = _max_negative_streak(ic_series)
    return sanitize_for_json(result)


def _yearly_metrics(rank_ic_df: pd.DataFrame, quantile_daily: pd.DataFrame, *, top_quantile: int) -> list[dict[str, Any]]:
    if rank_ic_df.empty:
        return []
    rank_copy = rank_ic_df.copy()
    rank_copy["year"] = rank_copy["trade_date"].dt.year
    q_top = (
        quantile_daily.loc[quantile_daily["quantile"].eq(top_quantile), ["trade_date", "avg_return"]]
        .rename(columns={"avg_return": "top_quantile_return"})
    )
    q_top["year"] = pd.to_datetime(q_top["trade_date"]).dt.year
    q_top_year = q_top.groupby("year")["top_quantile_return"]
    rows = []
    for year, group in rank_copy.groupby("year"):
        top_group = q_top_year.get_group(year) if year in q_top_year.groups else pd.Series(dtype=float)
        rows.append(
            {
                "year": int(year),
                "n_days": int(len(group)),
                "rank_ic_mean": group["rank_ic"].mean(),
                "rank_ic_win_rate": (group["rank_ic"] > 0).mean(),
                "top_quantile_return_mean": top_group.mean() if not top_group.empty else np.nan,
            }
        )
    return sanitize_for_json(rows)


def _size_bucket_rank_ic(frame: pd.DataFrame, factor_col: str, forward_col: str) -> dict[str, Any]:
    if "total_mv" not in frame.columns:
        return {"status": "placeholder", "reason": "total_mv column missing"}
    tagged = []
    for trade_date, group in frame.groupby("trade_date"):
        valid = group.loc[group["total_mv"].notna() & group["total_mv"].gt(0)].copy()
        if len(valid) < 9:
            continue
        valid["size_bucket"] = pd.qcut(
            valid["total_mv"].rank(method="first"),
            q=3,
            labels=["small", "mid", "large"],
        )
        tagged.append(valid)
    if not tagged:
        return {}
    tagged_df = pd.concat(tagged, ignore_index=True)
    result = {}
    for bucket, bucket_frame in tagged_df.groupby("size_bucket"):
        rank_ic_df = compute_rank_ic(bucket_frame, factor_col, forward_col)
        result[str(bucket)] = _ic_stats(rank_ic_df["rank_ic"] if not rank_ic_df.empty else pd.Series(dtype=float), rolling_window=252)
    return sanitize_for_json(result)


def _annualized_metrics(returns: pd.Series, equity: pd.Series) -> tuple[float, float, float, float, float]:
    if returns.empty:
        return np.nan, np.nan, np.nan, np.nan, np.nan
    ann_return = returns.mean() * TRADING_DAYS_PER_YEAR
    ann_vol = returns.std(ddof=0) * sqrt(TRADING_DAYS_PER_YEAR)
    sharpe = ann_return / ann_vol if ann_vol > 0 else np.nan
    drawdown = pd.Series(equity) / pd.Series(equity).cummax() - 1.0
    max_dd = drawdown.min() if not drawdown.empty else np.nan
    calmar = ann_return / abs(max_dd) if max_dd < 0 else np.nan
    return ann_return, ann_vol, sharpe, calmar, max_dd


def _adjacent_t_stats(spread_daily: pd.DataFrame) -> dict[str, Any]:
    result = {}
    quantiles = sorted(spread_daily.columns.tolist())
    for left, right in zip(quantiles[:-1], quantiles[1:]):
        diff = (spread_daily[right] - spread_daily[left]).dropna()
        result[f"Q{right}-Q{left}"] = _series_t_stat(diff)
    return sanitize_for_json(result)


def _series_t_stat(series: pd.Series) -> float:
    clean = pd.Series(series).dropna()
    if clean.empty:
        return np.nan
    std = clean.std(ddof=0)
    if std <= 0:
        return np.nan
    return float(clean.mean() / (std / sqrt(len(clean))))


def _monotonicity_flag(quantile_summary: pd.DataFrame) -> str:
    if quantile_summary.empty:
        return "unknown"
    ordered = quantile_summary.sort_values("quantile")["mean_return"]
    if ordered.is_monotonic_increasing:
        return "increasing"
    if ordered.is_monotonic_decreasing:
        return "decreasing"
    return "mixed"


def _ic_half_life_from_autocorr(autocorr_df: pd.DataFrame) -> int | None:
    if autocorr_df.empty:
        return None
    initial = autocorr_df["mean_autocorr"].iloc[0]
    if pd.isna(initial) or initial == 0:
        return None
    threshold = abs(initial) / 2.0
    for _, row in autocorr_df.iterrows():
        if pd.isna(row["mean_autocorr"]):
            continue
        if abs(row["mean_autocorr"]) <= threshold:
            return int(row["lag"])
    return None


def _single_year_concentration(yearly: list[dict[str, Any]]) -> dict[str, Any]:
    if not yearly:
        return {}
    positive = [row for row in yearly if (row.get("top_quantile_return_mean") or 0) > 0]
    return sanitize_for_json(
        {
            "positive_years": len(positive),
            "total_years": len(yearly),
            "has_single_year_concentration": len(positive) <= 1 and len(yearly) > 1,
        }
    )


def _max_negative_streak(series: pd.Series) -> int:
    streak = 0
    max_streak = 0
    for value in pd.Series(series).dropna():
        if value < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def _percentile_rank(candidate: float, population: list[float], *, higher_is_better: bool) -> float:
    arr = np.asarray(population, dtype=float)
    if not higher_is_better:
        arr = -arr
        candidate = -candidate
    return float((arr <= candidate).mean())
