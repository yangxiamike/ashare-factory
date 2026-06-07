from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .metrics import sanitize_for_json, to_plain_dict


def wide_to_long_factor_values(
    factor_df: pd.DataFrame,
    *,
    factor_id: str,
    raw_factor_col: str = "factor_value_raw",
    processed_factor_col: str = "factor_value_processed",
) -> pd.DataFrame:
    required = {"trade_date", "ts_code", raw_factor_col, processed_factor_col}
    missing = required - set(factor_df.columns)
    if missing:
        raise ValueError(f"missing columns for long-format export: {sorted(missing)}")
    return factor_df.loc[:, ["trade_date", "ts_code", raw_factor_col, processed_factor_col]].rename(
        columns={
            raw_factor_col: "factor_value_raw",
            processed_factor_col: "factor_value_processed",
        }
    ).assign(factor_id=factor_id)[
        ["trade_date", "ts_code", "factor_id", "factor_value_raw", "factor_value_processed"]
    ]


def long_to_wide_factor_values(
    factor_df: pd.DataFrame,
    *,
    value_col: str = "factor_value_processed",
) -> pd.DataFrame:
    required = {"trade_date", "ts_code", "factor_id", value_col}
    missing = required - set(factor_df.columns)
    if missing:
        raise ValueError(f"missing columns for wide-format export: {sorted(missing)}")
    return factor_df.pivot(index=["trade_date", "ts_code"], columns="factor_id", values=value_col).reset_index()


def update_factor_library(
    eval_result: dict[str, Any] | Any,
    *,
    library_path: str | Path | None = None,
) -> dict[str, Any]:
    result = to_plain_dict(eval_result)
    path = Path(library_path or result.get("output_paths", {}).get("factor_library_json") or "outputs/factor_library/factor_library.json")
    factor_id = result["factor_id"]
    summary = _build_library_summary(result)

    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    else:
        current = {"factors": {}}

    current.setdefault("factors", {})
    current["factors"][factor_id] = summary
    current["updated_at"] = result.get("evaluated_at")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize_for_json(current), ensure_ascii=False, indent=2), encoding="utf-8")

    result.setdefault("output_paths", {})
    result["output_paths"]["factor_library_json"] = str(path)
    result["factor_library_entry"] = summary
    return sanitize_for_json(current)


def _build_library_summary(result: dict[str, Any]) -> dict[str, Any]:
    full_sample = result.get("metrics", {}).get("full_sample", {})
    gate = result.get("gate_decision", {})
    return sanitize_for_json(
        {
            "factor_id": result["factor_id"],
            "status": gate.get("status", "candidate"),
            "last_run_id": result.get("run_id"),
            "last_evaluated_at": result.get("evaluated_at"),
            "mean_rank_ic": full_sample.get("rank_ic", {}).get("mean"),
            "ic_ir": full_sample.get("rank_ic", {}).get("ir"),
            "long_short_sharpe": full_sample.get("long_short", {}).get("sharpe"),
            "max_drawdown": full_sample.get("top_quantile", {}).get("max_drawdown"),
            "mean_turnover": full_sample.get("turnover", {}).get("mean_turnover"),
            "turnover_std": full_sample.get("turnover", {}).get("turnover_std"),
            "coverage_pct": full_sample.get("coverage_pct"),
            "reasons": gate.get("reasons", []),
            "output_paths": result.get("output_paths", {}),
        }
    )
