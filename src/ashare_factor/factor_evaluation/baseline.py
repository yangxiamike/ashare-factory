from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .metrics import compute_evaluation_metrics


def build_noise_baseline_evidence(
    factor_df: pd.DataFrame,
    *,
    processed_col: str,
    raw_col: str,
    forward_col: str,
    evaluation_cfg: dict[str, Any],
    gate_cfg: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    evidence_cfg = (gate_cfg.get("evidence") or {}).get("baseline_comparison", {})
    noise_names = evidence_cfg.get("noise", [])
    if isinstance(noise_names, dict):
        noise_names = noise_names.get("items", [])
    if not noise_names:
        return {}

    repeats = int(((gate_cfg.get("baseline_runtime") or {}).get("noise_repeats", 10)))
    rng = np.random.default_rng(20260607)
    rows: list[dict[str, Any]] = []
    for baseline_name in noise_names:
        for run_index in range(repeats):
            baseline_frame = _make_noise_frame(
                factor_df,
                baseline_name=baseline_name,
                processed_col=processed_col,
                raw_col=raw_col,
                rng=rng,
            )
            if baseline_frame is None:
                continue
            rows.append(
                _summarize_baseline_metrics(
                    baseline_frame,
                    baseline_name=baseline_name,
                    run_index=run_index,
                    forward_col=forward_col,
                    evaluation_cfg=evaluation_cfg,
                    gate_cfg=gate_cfg,
                )
            )
    return {"noise": rows}


def _make_noise_frame(
    factor_df: pd.DataFrame,
    *,
    baseline_name: str,
    processed_col: str,
    raw_col: str,
    rng: np.random.Generator,
) -> pd.DataFrame | None:
    frame = factor_df.copy()
    base_mask = frame[processed_col].notna()
    if not base_mask.any():
        return None

    if baseline_name == "random_normal":
        frame.loc[base_mask, "factor_value_processed"] = rng.standard_normal(base_mask.sum())
    elif baseline_name == "random_uniform":
        frame.loc[base_mask, "factor_value_processed"] = rng.uniform(-1.0, 1.0, base_mask.sum())
    elif baseline_name == "random_by_date_shuffle":
        frame["factor_value_processed"] = frame.groupby("trade_date")[processed_col].transform(
            lambda series: pd.Series(
                rng.permutation(series.to_numpy()),
                index=series.index,
            )
            if series.notna().any()
            else series
        )
    else:
        return None

    frame["factor_value_raw"] = frame["factor_value_processed"]
    frame["factor_value_for_eval"] = frame["factor_value_processed"]
    return frame


def _summarize_baseline_metrics(
    baseline_frame: pd.DataFrame,
    *,
    baseline_name: str,
    run_index: int,
    forward_col: str,
    evaluation_cfg: dict[str, Any],
    gate_cfg: dict[str, Any],
) -> dict[str, Any]:
    metrics = compute_evaluation_metrics(
        baseline_frame,
        factor_col="factor_value_processed",
        direction_col="factor_value_for_eval",
        raw_factor_col="factor_value_raw",
        forward_col=forward_col,
        n_quantiles=int(evaluation_cfg.get("n_quantiles", 5)),
        rebalance_days=int(evaluation_cfg.get("rebalance_days", 5)),
        rolling_ic_window=int(evaluation_cfg.get("rolling_ic_window", 252)),
        min_cross_section_count=int(evaluation_cfg.get("min_cross_section_count", 30)),
    )
    _, oos_frame = _split_oos_for_baseline(baseline_frame, gate_cfg=gate_cfg)
    oos_metrics = compute_evaluation_metrics(
        oos_frame,
        factor_col="factor_value_processed",
        direction_col="factor_value_for_eval",
        raw_factor_col="factor_value_raw",
        forward_col=forward_col,
        n_quantiles=int(evaluation_cfg.get("n_quantiles", 5)),
        rebalance_days=int(evaluation_cfg.get("rebalance_days", 5)),
        rolling_ic_window=int(evaluation_cfg.get("rolling_ic_window", 252)),
        min_cross_section_count=int(evaluation_cfg.get("min_cross_section_count", 30)),
    )
    return {
        "baseline_name": baseline_name,
        "run_index": run_index,
        "rank_ic_mean": metrics.get("rank_ic", {}).get("mean"),
        "top_quantile_return": metrics.get("top_quantile", {}).get("mean_return"),
        "top_quantile_sharpe": metrics.get("top_quantile", {}).get("sharpe"),
        "max_drawdown": metrics.get("top_quantile", {}).get("max_drawdown"),
        "mean_turnover": metrics.get("turnover", {}).get("mean_turnover"),
        "oos_rank_ic_mean": oos_metrics.get("rank_ic", {}).get("mean"),
    }


def _split_oos_for_baseline(
    frame: pd.DataFrame,
    *,
    gate_cfg: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    simple_oos = (gate_cfg.get("evidence") or {}).get("simple_oos", {})
    in_sample_pct = float(simple_oos.get("in_sample_pct", 0.75))
    dates = sorted(frame["trade_date"].dropna().unique().tolist())
    if len(dates) < 2:
        return frame.iloc[0:0].copy(), frame.copy()
    split_idx = max(1, min(len(dates) - 1, int(len(dates) * in_sample_pct)))
    split_date = dates[split_idx]
    return frame.loc[frame["trade_date"] < split_date].copy(), frame.loc[frame["trade_date"] >= split_date].copy()
