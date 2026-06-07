from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ashare_factor.models import EvaluationConfig, PreprocessConfig, SampleResult


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

    raw_coverage = float(merged["factor_value_raw"].notna().mean()) if len(merged) else 0.0
    if merged["factor_value_raw"].notna().sum() == 0:
        raise ValueError(f"calculation yielded all NaN (raw coverage={raw_coverage:.2%})")
    if merged["factor_value_raw"].dropna().nunique() == 1:
        raise ValueError(f"constant factor values (raw coverage={raw_coverage:.2%}, unique_non_null=1)")

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
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
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


def winsorize_mad(series: pd.Series, n: float = 3.0) -> pd.Series:
    med = series.median()
    mad = (series - med).abs().median()
    if pd.isna(mad) or mad == 0:
        return series
    return series.clip(med - n * 1.4826 * mad, med + n * 1.4826 * mad)


def cross_sectional_zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def neutralize_by_size(
    df: pd.DataFrame,
    factor_col: str,
    output_col: str = "factor_neutral",
) -> pd.DataFrame:
    result = df.copy()
    result[output_col] = np.nan
    for _, group in result.groupby("trade_date"):
        mask = group["total_mv"].notna() & (group["total_mv"] > 0) & group[factor_col].notna()
        if mask.sum() < 5:
            continue
        x = np.log(group.loc[mask, "total_mv"].values)
        y = group.loc[mask, factor_col].values
        design = np.column_stack([np.ones(len(x)), x])
        beta = np.linalg.lstsq(design, y, rcond=None)[0]
        resid = _standardize_residual(y - design @ beta)
        result.loc[group.index[mask], output_col] = resid
    return result


def neutralize_by_industry_and_size(
    df: pd.DataFrame,
    factor_col: str,
    industry_col: str = "sw_l1_name",
    output_col: str = "factor_industry_size_neutral",
) -> pd.DataFrame:
    result = df.copy()
    result[output_col] = np.nan
    for _, group in result.groupby("trade_date"):
        mask = (
            group["total_mv"].notna()
            & (group["total_mv"] > 0)
            & group[factor_col].notna()
            & group[industry_col].notna()
        )
        if mask.sum() < 10:
            continue
        industry_dummies = pd.get_dummies(group.loc[mask, industry_col], drop_first=True).astype(float)
        design = np.column_stack(
            [
                np.ones(mask.sum()),
                np.log(group.loc[mask, "total_mv"].values),
                industry_dummies.values,
            ]
        )
        y = group.loc[mask, factor_col].values
        beta = np.linalg.lstsq(design, y, rcond=None)[0]
        resid = _standardize_residual(y - design @ beta)
        result.loc[group.index[mask], output_col] = resid
    return result


def _standardize_residual(resid: np.ndarray) -> np.ndarray:
    std = resid.std(ddof=0)
    if pd.isna(std) or std == 0:
        return np.zeros_like(resid, dtype=float)
    return (resid - resid.mean()) / std


def _cross_sectional_zscore_preserve_nan(series: pd.Series) -> pd.Series:
    if series.notna().sum() == 0:
        return series
    return cross_sectional_zscore(series)
