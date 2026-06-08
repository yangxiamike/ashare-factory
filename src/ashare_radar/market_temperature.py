from __future__ import annotations

import math

import pandas as pd

from ashare_radar.models import MarketTemperatureResult


def evaluate_market_temperature(history_panel: pd.DataFrame, trade_date: str) -> MarketTemperatureResult:
    current = history_panel.loc[history_panel["trade_date"] == trade_date].copy()
    if current.empty:
        raise ValueError(f"no daily_panel rows found for trade_date={trade_date}")

    active = current.loc[~current["is_suspended"].fillna(False)].copy()
    if active.empty:
        raise ValueError(f"no active stocks found for trade_date={trade_date}")

    recent_turnover = (
        history_panel.groupby("trade_date", observed=True)["amount"].sum().sort_index().tail(5)
    )
    current_amount = float(active["amount"].fillna(0).sum())
    amount_ratio_5d = (
        current_amount / float(recent_turnover.mean())
        if not recent_turnover.empty and float(recent_turnover.mean()) != 0.0
        else None
    )

    up_count = int((active["pct_chg"] > 0).sum())
    down_count = int((active["pct_chg"] < 0).sum())
    up_limit_count = int((active["close"] >= active["up_limit"]).fillna(False).sum())
    down_limit_count = int((active["close"] <= active["down_limit"]).fillna(False).sum())
    breadth_ratio = up_count / max(up_count + down_count, 1)
    return_std = float(active["pct_chg"].std(ddof=0))
    average_return = float(active["pct_chg"].mean())
    median_return = float(active["pct_chg"].median())

    score = 50
    score += _score_average_return(average_return)
    score += _score_amount_ratio(amount_ratio_5d)
    score += _score_breadth(breadth_ratio)
    score += _score_limit_balance(up_limit_count, down_limit_count)
    score += _score_dispersion(return_std)
    score = max(0, min(100, score))

    if score >= 65:
        state = "risk_on"
    elif score <= 35:
        state = "risk_off"
    else:
        state = "neutral"

    return MarketTemperatureResult(
        trade_date=trade_date,
        score=score,
        state=state,
        metrics={
            "stock_count": int(len(active)),
            "average_return": round(average_return, 4),
            "median_return": round(median_return, 4),
            "amount_total": round(current_amount, 2),
            "amount_ratio_5d": _round_or_none(amount_ratio_5d),
            "up_count": up_count,
            "down_count": down_count,
            "breadth_ratio": round(breadth_ratio, 4),
            "up_limit_count": up_limit_count,
            "down_limit_count": down_limit_count,
            "return_std": round(return_std, 4) if not math.isnan(return_std) else 0.0,
        },
    )


def compute_market_temperature(history_panel: pd.DataFrame, trade_date: str) -> MarketTemperatureResult:
    return evaluate_market_temperature(history_panel=history_panel, trade_date=trade_date)


def _score_average_return(average_return: float) -> int:
    if average_return >= 1.5:
        return 20
    if average_return >= 0.5:
        return 10
    if average_return <= -1.5:
        return -20
    if average_return <= -0.5:
        return -10
    return 0


def _score_amount_ratio(amount_ratio_5d: float | None) -> int:
    if amount_ratio_5d is None:
        return 0
    if amount_ratio_5d >= 1.15:
        return 10
    if amount_ratio_5d >= 1.0:
        return 5
    if amount_ratio_5d <= 0.85:
        return -10
    if amount_ratio_5d <= 0.95:
        return -5
    return 0


def _score_breadth(breadth_ratio: float) -> int:
    if breadth_ratio >= 0.65:
        return 10
    if breadth_ratio >= 0.55:
        return 5
    if breadth_ratio <= 0.35:
        return -10
    if breadth_ratio <= 0.45:
        return -5
    return 0


def _score_limit_balance(up_limit_count: int, down_limit_count: int) -> int:
    balance = up_limit_count - down_limit_count
    if balance >= 20:
        return 10
    if balance >= 5:
        return 5
    if balance <= -20:
        return -10
    if balance <= -5:
        return -5
    return 0


def _score_dispersion(return_std: float) -> int:
    if math.isnan(return_std):
        return 0
    if return_std <= 2.0:
        return 10
    if return_std <= 3.5:
        return 5
    if return_std >= 6.0:
        return -10
    if return_std >= 4.5:
        return -5
    return 0


def _round_or_none(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None
