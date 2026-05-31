"""Single-factor analysis utilities — data loading, factor construction, IC, quantile returns."""

import duckdb
import numpy as np
import pandas as pd


# ── Data Loading ──────────────────────────────────────────────

def load_daily_panel(duckdb_path, start_date="20220101"):
    """Load daily_panel from duckdb, return clean DataFrame."""
    con = duckdb.connect(str(duckdb_path), read_only=True)
    sql = """
    SELECT trade_date, ts_code, close, adj_factor, total_mv, is_suspended, sw_l1_name
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
    return df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)


# ── Factor Construction ───────────────────────────────────────

def compute_momentum(df, window=20):
    """Compute momentum factor: adj_close / adj_close.shift(window) - 1"""
    df = df.copy()
    df["mom"] = df.groupby("ts_code")["adj_close"].transform(
        lambda s: s / s.shift(window) - 1
    )
    df = df[df["mom"].notna()].copy()
    return df


def compute_forward_returns(df, horizons=(1, 5, 20)):
    """Compute forward returns for given horizons."""
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


def neutralize_by_size(df, factor_col):
    """Cross-sectional size neutralization using log market cap residual."""
    df = df.copy()
    df["factor_neutral"] = np.nan
    for _, g in df.groupby("trade_date"):
        mask = g["total_mv"].notna() & (g["total_mv"] > 0) & g[factor_col].notna()
        if mask.sum() < 5:
            continue
        x = np.log(g.loc[mask, "total_mv"].values)
        y = g.loc[mask, factor_col].values
        X = np.column_stack([np.ones(len(x)), x])
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ beta
        resid = (resid - resid.mean()) / resid.std(ddof=0)
        df.loc[mask.index, "factor_neutral"] = resid
    return df


def build_factor(df, factor_col="mom", neutral=True):
    """Full factor preprocessing pipeline: winsorize → zscore → [neutralize]."""
    df = df.copy()
    df["factor_raw"] = df.groupby("trade_date")[factor_col].transform(winsorize_mad)
    df["factor_zscore"] = df.groupby("trade_date")["factor_raw"].transform(
        cross_sectional_zscore
    )
    if neutral:
        df = neutralize_by_size(df, "factor_zscore")
    return df


# ── Quantile Assignment ───────────────────────────────────────

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


# ── IC Analysis ──────────────────────────────────────────────

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
    return pd.DataFrame(records).sort_values("trade_date").reset_index(drop=True)


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


# ── Quantile Returns ──────────────────────────────────────────

def compute_quantile_returns(df, forward_col):
    """Compute mean forward return by quantile per date."""
    daily = (
        df.dropna(subset=["quantile", forward_col])
        .groupby(["trade_date", "quantile"])[forward_col]
        .mean()
        .reset_index()
        .rename(columns={forward_col: "avg_return"})
    )
    # Summary table
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
    # Pivot for cumulative
    pivot = daily.pivot(
        index="trade_date", columns="quantile", values="avg_return"
    ).sort_index()
    return summary, daily, pivot


def long_short_spread(pivot):
    """Compute Q5-Q1 long-short spread from quantile pivot."""
    ls = pd.DataFrame(
        {
            "trade_date": pivot.index,
            "spread": pivot.get(5, 0) - pivot.get(1, 0),
        }
    )
    ls["cum_spread"] = (1 + ls["spread"].fillna(0)).cumprod() - 1
    return ls


def ls_summary(ls):
    """Summarize long-short performance."""
    s = ls["spread"].dropna()
    cum = (1 + s).cumprod()
    dd = cum / cum.cummax() - 1
    return {
        "mean": s.mean(),
        "std": s.std(ddof=0),
        "win_rate": (s > 0).mean(),
        "cum_return": cum.iloc[-1] - 1,
        "max_dd": dd.min(),
    }


# ── Stability ─────────────────────────────────────────────────

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
