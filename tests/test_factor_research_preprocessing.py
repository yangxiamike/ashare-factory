import numpy as np
import pandas as pd

from ashare_factor.factor_research.preprocessing import (
    neutralize_by_industry_and_size,
    preprocess_factor,
)
from ashare_factor.models import PreprocessConfig


def test_neutralize_by_industry_and_size_removes_linear_exposures() -> None:
    total_mv = np.linspace(100.0, 1200.0, 12)
    industry = np.array(["Bank"] * 6 + ["Tech"] * 6)
    residual_seed = np.array(
        [-0.3, 0.2, -0.1, 0.4, -0.2, 0.0, 0.1, -0.4, 0.3, -0.2, 0.2, 0.0]
    )
    frame = pd.DataFrame(
        {
            "trade_date": pd.Timestamp("2024-01-02"),
            "ts_code": [f"{i:06d}.SZ" for i in range(12)],
            "total_mv": total_mv,
            "sw_l1_name": industry,
            "factor_value_zscore": 2.0 * np.log(total_mv) + (industry == "Tech") * 3.0 + residual_seed,
        }
    )

    result = neutralize_by_industry_and_size(frame, "factor_value_zscore")
    neutral = result["factor_industry_size_neutral"]

    assert neutral.notna().sum() == 12
    assert abs(neutral.mean()) < 1e-12
    assert abs(neutral.std(ddof=0) - 1.0) < 1e-12
    assert abs(neutral.corr(pd.Series(np.log(total_mv)))) < 1e-12
    assert abs(neutral.corr(pd.Series((industry == "Tech").astype(float)))) < 1e-12


def test_preprocess_factor_runs_without_factor_utils_dependency() -> None:
    total_mv = np.linspace(100.0, 1200.0, 12)
    industry = np.array(["Bank"] * 6 + ["Tech"] * 6)
    factor_values = pd.DataFrame(
        {
            "trade_date": pd.Timestamp("2024-01-02"),
            "ts_code": [f"{i:06d}.SZ" for i in range(12)],
            "factor_id": "momentum_20d_v1",
            "factor_value_raw": 2.0 * np.log(total_mv) + (industry == "Tech") * 3.0,
        }
    )
    sample = pd.DataFrame(
        {
            "trade_date": pd.Timestamp("2024-01-02"),
            "ts_code": [f"{i:06d}.SZ" for i in range(12)],
            "total_mv": total_mv,
            "sw_l1_name": industry,
        }
    )

    result = preprocess_factor(
        factor_values,
        sample,
        config=PreprocessConfig(neutralize="industry_size"),
    )

    assert list(result.columns) == [
        "trade_date",
        "ts_code",
        "factor_id",
        "factor_value_raw",
        "factor_value_winsorized",
        "factor_value_zscore",
        "factor_value_neutral",
        "factor_value_processed",
    ]
    assert result["factor_value_neutral"].notna().sum() == 12
    assert abs(result["factor_value_processed"].mean()) < 1e-12
    assert abs(result["factor_value_processed"].std(ddof=0) - 1.0) < 1e-12
