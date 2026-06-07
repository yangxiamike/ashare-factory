from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from factor_utils import (
    cross_sectional_zscore,
    neutralize_by_industry_and_size,
    neutralize_by_size,
    winsorize_mad,
)

from ashare_factor.models import EvaluationConfig, PreprocessConfig, SampleResult, load_yaml_like


DEFAULT_EVALUATION_PATH = Path("configs/evaluation.yaml")


def preprocess_factor(
    factor_values: pd.DataFrame,
    sample: SampleResult | pd.DataFrame,
    *,
    config: EvaluationConfig | PreprocessConfig | None = None,
    config_path: str | Path = DEFAULT_EVALUATION_PATH,
) -> pd.DataFrame:
    preprocess_config = _resolve_preprocess_config(config=config, config_path=config_path)
    sample_frame = sample.sample if isinstance(sample, SampleResult) else sample
    merged = factor_values.merge(
        sample_frame[["trade_date", "ts_code", "total_mv", "sw_l1_name"]],
        on=["trade_date", "ts_code"],
        how="left",
        validate="one_to_one",
    ).sort_values(["trade_date", "ts_code"])

    if merged["factor_value_raw"].notna().sum() == 0:
        raise ValueError("calculation yielded all NaN")
    if merged["factor_value_raw"].dropna().nunique() == 1:
        raise ValueError("constant factor values")

    merged["factor_value_winsorized"] = merged.groupby("trade_date")["factor_value_raw"].transform(
        lambda series: winsorize_mad(series, n=preprocess_config.winsorize_n_mad)
    )
    merged["factor_value_zscore"] = merged.groupby("trade_date")["factor_value_winsorized"].transform(
        _cross_sectional_zscore_preserve_nan
    )

    neutralize_mode = preprocess_config.neutralize
    if neutralize_mode == "size":
        merged = neutralize_by_size(merged, "factor_value_zscore", output_col="factor_value_neutral")
    elif neutralize_mode == "industry_size":
        merged = neutralize_by_industry_and_size(
            merged,
            "factor_value_zscore",
            output_col="factor_value_neutral",
        )
    elif neutralize_mode == "none":
        merged["factor_value_neutral"] = merged["factor_value_zscore"]
    else:
        raise ValueError(f"Unsupported neutralize mode: {neutralize_mode}")

    if preprocess_config.re_standardize_after_neutralize:
        merged["factor_value_processed"] = merged.groupby("trade_date")["factor_value_neutral"].transform(
            _cross_sectional_zscore_preserve_nan
        )
    else:
        merged["factor_value_processed"] = merged["factor_value_neutral"]

    return merged[
        [
            "trade_date",
            "ts_code",
            "factor_id",
            "factor_value_raw",
            "factor_value_winsorized",
            "factor_value_zscore",
            "factor_value_neutral",
            "factor_value_processed",
        ]
    ].reset_index(drop=True)


def _resolve_preprocess_config(
    *,
    config: EvaluationConfig | PreprocessConfig | None,
    config_path: str | Path,
) -> PreprocessConfig:
    if isinstance(config, PreprocessConfig):
        return config
    if isinstance(config, EvaluationConfig):
        return config.preprocess
    return load_evaluation_config(config_path).preprocess


def load_evaluation_config(path: str | Path = DEFAULT_EVALUATION_PATH) -> EvaluationConfig:
    payload = load_yaml_like(path)
    preprocess: dict[str, Any] = payload.get("preprocess", {})
    winsorize = preprocess.get("winsorize", {})
    return EvaluationConfig(
        preprocess=PreprocessConfig(
            winsorize_method=str(winsorize.get("method", "mad")),
            winsorize_n_mad=float(winsorize.get("n_mad", 3.0)),
            neutralize=str(preprocess.get("neutralize", "industry_size")),
            re_standardize_after_neutralize=bool(
                preprocess.get("re_standardize_after_neutralize", True)
            ),
        ),
        evaluation=dict(payload.get("evaluation", {})),
        gate=dict(payload.get("gate", {})),
    )


def _cross_sectional_zscore_preserve_nan(series: pd.Series) -> pd.Series:
    if series.notna().sum() == 0:
        return series
    return cross_sectional_zscore(series)
