"""Single-factor analysis utilities: data loading, factor construction, IC, returns."""

import duckdb
import numpy as np
import pandas as pd


DAILY_PANEL_REQUIRED_COLUMNS = [
    "trade_date",
    "ts_code",
    "close",
    "adj_factor",
    "total_mv",
    "is_suspended",
    "sw_l1_name",
]
DAILY_PANEL_OPTIONAL_COLUMNS = ["open", "up_limit", "down_limit"]


def load_daily_panel(duckdb_path, start_date="20220101"):
    """Load daily_panel from duckdb, return clean DataFrame."""
    con = duckdb.connect(str(duckdb_path), read_only=True)
    available_columns = {
        row[0]
        for row in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = 'daily_panel'
            """
        ).fetchall()
    }
    select_columns = DAILY_PANEL_REQUIRED_COLUMNS + [
        col for col in DAILY_PANEL_OPTIONAL_COLUMNS if col in available_columns
    ]
    sql = f"""
    SELECT {", ".join(select_columns)}
    FROM daily_panel
    WHERE trade_date >= ?
      AND close IS NOT NULL
      AND total_mv IS NOT NULL
    ORDER BY trade_date, ts_code
    """
    df = con.execute(sql, [start_date]).fetchdf()
    con.close()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["is_suspended"] = df["is_suspended"].fillna(False).astype(bool)
    df["adj_close"] = df["close"] * df["adj_factor"]
    df = df[~df["is_suspended"] & (df["total_mv"] > 0)].copy()
    if {"open", "up_limit"}.issubset(df.columns):
        df["is_limit_up_at_open"] = df["open"].notna() & df["up_limit"].notna() & (
            df["open"] >= df["up_limit"]
        )
        df["next_open_is_limit_up"] = df.groupby("ts_code")["is_limit_up_at_open"].shift(-1)
    return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


def compute_momentum(df, window=20, col_name="mom", dropna=True):
    """Compute momentum factor: adj_close / adj_close.shift(window) - 1."""
    df = df.copy()
    df[col_name] = df.groupby("ts_code")["adj_close"].transform(
        lambda s: s / s.shift(window) - 1
    )
    if dropna:
        df = df[df[col_name].notna()].copy()
    return df


def compute_forward_returns(df, horizons=(1, 5, 20)):
    """Compute forward returns avoiding same-day look-ahead.

    fwd_{h}d = adj_close[t+h+1] / adj_close[t+1] - 1, i.e. the h-day return
    starting from the next trading day after the factor observation.
    """
    df = df.copy()
    for h in horizons:
        df[f"fwd_{h}d"] = df.groupby("ts_code")["adj_close"].transform(
            lambda s: s.shift(-(h + 1)) / s.shift(-1) - 1
        )
    return df


def winsorize_mad(series, n=3.0):
    """MAD winsorization per cross-section."""
    med = series.median()
    mad = (series - med).abs().median()
    if pd.isna(mad) or mad == 0:
        return series
    return series.clip(med - n * 1.4826 * mad, med + n * 1.4826 * mad)


def cross_sectional_zscore(series):
    """Cross-sectional z-score standardization."""
    std = series.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def _standardize_residual(resid):
    std = resid.std(ddof=0)
    if pd.isna(std) or std == 0:
        return np.zeros_like(resid, dtype=float)
    return (resid - resid.mean()) / std


def neutralize_by_size(df, factor_col, output_col="factor_neutral"):
    """Cross-sectional size neutralization using log market cap residual."""
    df = df.copy()
    df[output_col] = np.nan
    for _, g in df.groupby("trade_date"):
        mask = g["total_mv"].notna() & (g["total_mv"] > 0) & g[factor_col].notna()
        if mask.sum() < 5:
            continue
        x = np.log(g.loc[mask, "total_mv"].values)
        y = g.loc[mask, factor_col].values
        X = np.column_stack([np.ones(len(x)), x])
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = _standardize_residual(y - X @ beta)
        df.loc[g.index[mask], output_col] = resid
    return df


def neutralize_by_industry_and_size(
    df,
    factor_col,
    industry_col="sw_l1_name",
    output_col="factor_industry_size_neutral",
):
    """Cross-sectional industry and size neutralization using regression residuals."""
    df = df.copy()
    df[output_col] = np.nan
    for _, g in df.groupby("trade_date"):
        mask = (
            g["total_mv"].notna()
            & (g["total_mv"] > 0)
            & g[factor_col].notna()
            & g[industry_col].notna()
        )
        if mask.sum() < 10:
            continue
        industry_dummies = pd.get_dummies(g.loc[mask, industry_col], drop_first=True).astype(float)
        X = np.column_stack(
            [
                np.ones(mask.sum()),
                np.log(g.loc[mask, "total_mv"].values),
                industry_dummies.values,
            ]
        )
        y = g.loc[mask, factor_col].values
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = _standardize_residual(y - X @ beta)
        df.loc[g.index[mask], output_col] = resid
    return df


def build_factor(
    df,
    factor_col="mom",
    neutral=True,
    neutralization="size",
    industry_col="sw_l1_name",
    output_col="factor_neutral",
):
    """Full factor preprocessing pipeline: winsorize -> zscore -> optional neutralize."""
    assert neutralization in {"size", "industry_size"}
    df = df.copy()
    df["factor_raw"] = df.groupby("trade_date")[factor_col].transform(winsorize_mad)
    df["factor_zscore"] = df.groupby("trade_date")["factor_raw"].transform(
        cross_sectional_zscore
    )
    if neutral:
        if neutralization == "size":
            df = neutralize_by_size(df, "factor_zscore", output_col=output_col)
        else:
            df = neutralize_by_industry_and_size(
                df,
                "factor_zscore",
                industry_col=industry_col,
                output_col=output_col,
            )
    return df


def assign_quantiles(df, factor_col, n_quantiles=5):
    """Assign quantile groups (1..n_quantiles) per date."""
    df = df.copy()
    df["quantile"] = pd.NA
    for _, g in df.groupby("trade_date"):
        mask = g[factor_col].notna()
        if mask.sum() < n_quantiles:
            continue
        df.loc[g.index[mask], "quantile"] = pd.qcut(
            g.loc[mask, factor_col].rank(method="first"),
            q=n_quantiles,
            labels=list(range(1, n_quantiles + 1)),
        ).astype(int)
    df["quantile"] = df["quantile"].astype("Int64")
    return df


def compute_rank_ic(df, factor_col, forward_col):
    """Compute daily rank IC between factor and forward return."""
    records = []
    for dt, g in df.groupby("trade_date"):
        valid = g[[factor_col, forward_col]].dropna()
        if len(valid) < 10:
            continue
        r_factor = valid[factor_col].rank()
        r_forward = valid[forward_col].rank()
        ic = r_factor.corr(r_forward)
        records.append({"trade_date": dt, "rank_ic": ic, "n_stocks": len(valid)})
    columns = ["trade_date", "rank_ic", "n_stocks"]
    return pd.DataFrame(records, columns=columns).sort_values("trade_date").reset_index(drop=True)


def ic_summary(ic_df):
    """Summarize IC statistics."""
    ic = ic_df["rank_ic"].dropna()
    return {
        "mean_ic": ic.mean(),
        "std_ic": ic.std(ddof=0),
        "ic_ir": ic.mean() / ic.std(ddof=0) if ic.std(ddof=0) > 0 else np.nan,
        "win_rate": (ic > 0).mean(),
        "n_days": len(ic),
    }


def compute_ic_decay(df, factor_col, max_lag=20):
    """Compute rank IC summary for forward horizons 1..max_lag."""
    records = []
    for horizon in range(1, max_lag + 1):
        forward_col = f"fwd_{horizon}d"
        if forward_col not in df.columns:
            continue
        ic_df = compute_rank_ic(df, factor_col, forward_col)
        ic = ic_df["rank_ic"].dropna()
        if ic.empty:
            continue
        std_ic = ic.std(ddof=0)
        records.append(
            {
                "horizon": horizon,
                "mean_ic": ic.mean(),
                "std_ic": std_ic,
                "ic_ir": ic.mean() / std_ic if std_ic > 0 else np.nan,
            }
        )
    return pd.DataFrame(records)


def compute_quantile_returns(df, forward_col):
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
    summary["hit_rate"] = (
        daily.groupby("quantile")["avg_return"]
        .apply(lambda s: (s > 0).mean())
        .values
    )
    pivot = daily.pivot(
        index="trade_date", columns="quantile", values="avg_return"
    ).sort_index()
    return summary, daily, pivot


def rebalance_cumulative_returns(returns, step=5):
    """Compound overlapping forward returns only on rebalance observations."""
    assert step >= 1
    sampled = returns.fillna(0).iloc[::step]
    cumulative = (1 + sampled).cumprod() - 1
    return cumulative.reindex(returns.index).ffill()


def long_short_spread(pivot, step=5):
    """Compute Q5-Q1 long-short spread from quantile pivot."""
    ls = pd.DataFrame(
        {
            "trade_date": pivot.index,
            "spread": pivot.get(5, 0) - pivot.get(1, 0),
        }
    )
    ls["cum_spread"] = rebalance_cumulative_returns(ls["spread"], step=step).to_numpy()
    return ls


def ls_summary(ls):
    """Summarize long-short performance."""
    s = ls["spread"].dropna()
    equity = 1 + ls["cum_spread"].fillna(0)
    dd = equity / equity.cummax() - 1
    return {
        "mean": s.mean(),
        "std": s.std(ddof=0),
        "win_rate": (s > 0).mean(),
        "cum_return": ls["cum_spread"].iloc[-1],
        "max_dd": dd.min(),
    }


def factor_autocorr(df, factor_col):
    """Compute rank autocorrelation of factor between consecutive dates."""
    dates = sorted(df["trade_date"].unique())
    rows = []
    for d1, d2 in zip(dates[:-1], dates[1:]):
        prev = df[df["trade_date"] == d1][["ts_code", factor_col]].rename(
            columns={factor_col: "f_prev"}
        )
        curr = df[df["trade_date"] == d2][["ts_code", factor_col]].rename(
            columns={factor_col: "f_curr"}
        )
        m = prev.merge(curr, on="ts_code")
        if len(m) < 10:
            continue
        rows.append(
            {
                "trade_date": d2,
                "autocorr": m["f_prev"].rank().corr(m["f_curr"].rank()),
                "n_overlap": len(m),
            }
        )
    return pd.DataFrame(rows)
