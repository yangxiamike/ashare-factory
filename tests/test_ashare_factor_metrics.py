import numpy as np
import pandas as pd

from ashare_factor.factor_evaluation.metrics import (
    assign_quantiles,
    compute_quantile_returns,
    compute_evaluation_metrics,
    compute_rank_ic,
    factor_autocorr_multi_lag,
    factor_industry_exposure,
    long_short_spread,
)


def test_metrics_helpers_match_expected_quantile_and_spread_behavior() -> None:
    dates = pd.to_datetime(["2024-01-02"] * 10 + ["2024-01-03"] * 10)
    tickers = [f"{idx:06d}.SZ" for idx in range(10)] * 2
    factor = list(range(10)) + list(range(10))
    forward = list(range(10)) + list(range(9, -1, -1))
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "ts_code": tickers,
            "factor": factor,
            "forward_5d": forward,
        }
    )

    quantiled = assign_quantiles(frame, "factor", n_quantiles=5)

    assert quantiled.loc[quantiled["trade_date"].eq(pd.Timestamp("2024-01-02")), "quantile"].tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]

    summary, daily, pivot = compute_quantile_returns(quantiled, "forward_5d")

    assert summary["quantile"].tolist() == [1, 2, 3, 4, 5]
    assert daily["avg_return"].tolist() == [0.5, 2.5, 4.5, 6.5, 8.5, 8.5, 6.5, 4.5, 2.5, 0.5]

    spread = long_short_spread(pivot, step=1)
    np.testing.assert_allclose(spread["spread"], [8.0, -8.0])
    np.testing.assert_allclose(spread["cum_spread"], [8.0, -64.0])


def test_metrics_helpers_match_expected_ic_autocorr_and_industry_behavior() -> None:
    dates = pd.to_datetime(["2024-01-02"] * 10 + ["2024-01-03"] * 10)
    tickers = [f"{idx:06d}.SZ" for idx in range(10)] * 2
    factor = list(range(10)) + list(range(10))
    forward = list(range(10)) + list(range(9, -1, -1))
    industries = ["Bank"] * 5 + ["Tech"] * 5 + ["Bank"] * 5 + ["Tech"] * 5
    frame = pd.DataFrame(
        {
            "trade_date": dates,
            "ts_code": tickers,
            "factor": factor,
            "forward_5d": forward,
            "sw_l1_name": industries,
        }
    )

    rank_ic = compute_rank_ic(frame, "factor", "forward_5d")
    np.testing.assert_allclose(rank_ic["rank_ic"], [1.0, -1.0])
    assert rank_ic["n_stocks"].tolist() == [10, 10]

    autocorr = factor_autocorr_multi_lag(frame, "factor", max_lag=2)
    np.testing.assert_allclose(autocorr.loc[autocorr["lag"].eq(1), "mean_autocorr"], [1.0])
    assert np.isnan(autocorr.loc[autocorr["lag"].eq(2), "mean_autocorr"]).all()

    exposure = factor_industry_exposure(frame, "factor")
    assert exposure["industry"].tolist() == ["Tech", "Bank"]
    np.testing.assert_allclose(exposure["mean_exposure"], [7.0, 2.0])
    np.testing.assert_allclose(exposure["normalized_exposure"], [4.949747468305833, 1.414213562373095])


def test_compute_evaluation_metrics_uses_localized_helpers() -> None:
    rows = []
    for trade_date, forward_values in [
        (pd.Timestamp("2024-01-02"), list(range(30))),
        (pd.Timestamp("2024-01-03"), list(range(29, -1, -1))),
    ]:
        for idx, forward in enumerate(forward_values):
            rows.append(
                {
                    "trade_date": trade_date,
                    "ts_code": f"{idx:06d}.SZ",
                    "factor": float(idx),
                    "factor_raw": float(idx),
                    "forward_5d": float(forward),
                    "total_mv": float(idx + 100),
                    "sw_l1_name": "Bank" if idx < 15 else "Tech",
                }
            )
    frame = pd.DataFrame(rows)

    result = compute_evaluation_metrics(
        frame,
        factor_col="factor",
        direction_col="factor",
        forward_col="forward_5d",
        raw_factor_col="factor_raw",
        n_quantiles=5,
        rebalance_days=1,
        min_cross_section_count=10,
    )

    assert result["n_valid_dates"] == 2
    assert result["rank_ic"]["mean"] == 0.0
    assert result["quantile"]["monotonicity"] == "increasing"
    assert result["stability"]["autocorr_decay"][0]["mean_autocorr"] == 1.0
