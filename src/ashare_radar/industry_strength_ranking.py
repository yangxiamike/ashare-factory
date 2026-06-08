from __future__ import annotations

import pandas as pd

from ashare_radar.models import IndustryPerformance, IndustryStrengthRankingResult


DEFAULT_RETURN_METHOD = "stock_aggregate"


def rank_industry_strength(
    history_panel: pd.DataFrame,
    trade_date: str,
    return_method: str = DEFAULT_RETURN_METHOD,
) -> IndustryStrengthRankingResult:
    if return_method != DEFAULT_RETURN_METHOD:
        raise ValueError(f"unsupported industry return method: {return_method}")

    current = history_panel.loc[history_panel["trade_date"] == trade_date].copy()
    if current.empty:
        raise ValueError(f"no daily_panel rows found for trade_date={trade_date}")

    active = current.loc[
        (~current["is_suspended"].fillna(False)) & current["sw_l1_name"].notna()
    ].copy()
    if active.empty:
        raise ValueError(f"no active industry rows found for trade_date={trade_date}")

    grouped = (
        active.groupby("sw_l1_name", observed=True)
        .agg(
            mean_return=("pct_chg", "mean"),
            median_return=("pct_chg", "median"),
            total_amount=("amount", "sum"),
            stock_count=("ts_code", "count"),
            advancer_ratio=("pct_chg", lambda values: float((values > 0).mean())),
        )
        .reset_index()
    )

    amount_ratio = _build_industry_amount_ratio(history_panel, trade_date)
    grouped = grouped.merge(amount_ratio, on="sw_l1_name", how="left")

    ranked = grouped.sort_values(["mean_return", "total_amount"], ascending=[False, False])
    weakest = grouped.sort_values(["mean_return", "total_amount"], ascending=[True, False])
    volume_ranked = grouped.sort_values(
        ["amount_ratio_5d", "total_amount"],
        ascending=[False, False],
        na_position="last",
    )

    breadth = {
        "industry_count": int(len(grouped)),
        "positive_industry_ratio": round(float((grouped["mean_return"] > 0).mean()), 4),
        "negative_industry_ratio": round(float((grouped["mean_return"] < 0).mean()), 4),
        "median_industry_return": round(float(grouped["mean_return"].median()), 4),
    }
    return IndustryStrengthRankingResult(
        trade_date=trade_date,
        return_method=return_method,
        top=_to_industry_list(ranked.head(5)),
        bottom=_to_industry_list(weakest.head(5)),
        volume_leaders=_to_industry_list(volume_ranked.head(5)),
        breadth=breadth,
    )


def rank_industries(
    history_panel: pd.DataFrame,
    trade_date: str,
    return_method: str = DEFAULT_RETURN_METHOD,
) -> IndustryStrengthRankingResult:
    return rank_industry_strength(
        history_panel=history_panel,
        trade_date=trade_date,
        return_method=return_method,
    )


def _build_industry_amount_ratio(history_panel: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    industry_amount = (
        history_panel.loc[history_panel["sw_l1_name"].notna()]
        .groupby(["trade_date", "sw_l1_name"], observed=True)["amount"]
        .sum()
        .reset_index()
        .sort_values(["sw_l1_name", "trade_date"])
    )
    industry_amount["amount_avg_5d"] = industry_amount.groupby("sw_l1_name", observed=True)[
        "amount"
    ].transform(lambda values: values.rolling(5, min_periods=1).mean())
    current = industry_amount.loc[industry_amount["trade_date"] == trade_date].copy()
    current["amount_ratio_5d"] = current["amount"] / current["amount_avg_5d"]
    return current[["sw_l1_name", "amount_ratio_5d"]]


def _to_industry_list(frame: pd.DataFrame) -> list[IndustryPerformance]:
    return [
        IndustryPerformance(
            industry_name=str(row.sw_l1_name),
            mean_return=float(row.mean_return),
            median_return=float(row.median_return),
            total_amount=float(row.total_amount),
            stock_count=int(row.stock_count),
            advancer_ratio=float(row.advancer_ratio),
            amount_ratio_5d=float(row.amount_ratio_5d) if pd.notna(row.amount_ratio_5d) else None,
        )
        for row in frame.itertuples(index=False)
    ]
