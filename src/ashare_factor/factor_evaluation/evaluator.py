from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .gate import apply_gate
from .metrics import compare_with_baselines, compute_evaluation_metrics, sanitize_for_json, to_plain_dict


def evaluate_factor(
    factor_df: pd.DataFrame,
    factor_spec: dict[str, Any] | Any,
    evaluation_config: dict[str, Any] | Any,
    *,
    factor_id: str | None = None,
    factor_col: str | None = None,
    raw_factor_col: str | None = None,
    duckdb_path: str | Path | None = None,
    registry_path: str | Path | None = None,
    universe_path: str | Path | None = None,
    evaluation_path: str | Path | None = "configs/evaluation.yaml",
    baseline_evidence: dict[str, Any] | None = None,
    run_id: str | None = None,
    output_root: str | Path = "outputs",
    persist_json: bool = False,
) -> dict[str, Any]:
    spec = to_plain_dict(factor_spec)
    config = to_plain_dict(evaluation_config)
    eval_cfg = config.get("evaluation", {})
    factor_id = factor_id or spec.get("factor_id") or spec.get("name") or "unknown_factor"
    direction = spec.get("direction", "positive")
    primary_horizon = int(eval_cfg.get("primary_horizon", 5))
    forward_col = f"fwd_{primary_horizon}d"
    processed_col = _resolve_factor_col(factor_df, factor_col, preferred=["factor_value_processed", "factor_processed", factor_id])
    raw_col = _resolve_factor_col(factor_df, raw_factor_col, preferred=["factor_value_raw", "factor_raw", processed_col])

    frame = factor_df.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    if processed_col != "factor_value_processed":
        frame = frame.rename(columns={processed_col: "factor_value_processed"})
        processed_col = "factor_value_processed"
    if raw_col != "factor_value_raw":
        frame = frame.rename(columns={raw_col: "factor_value_raw"})
        raw_col = "factor_value_raw"

    sign = 1.0 if direction == "positive" else -1.0
    frame["factor_value_for_eval"] = frame[processed_col] * sign

    validity_checks = {
        "all_nan": bool(frame[raw_col].dropna().empty),
        "constant_factor": bool(frame[raw_col].dropna().nunique() <= 1 if not frame[raw_col].dropna().empty else False),
    }
    if forward_col not in frame.columns:
        raise ValueError(f"missing forward return column: {forward_col}")

    full_metrics = compute_evaluation_metrics(
        frame,
        factor_col=processed_col,
        direction_col="factor_value_for_eval",
        raw_factor_col=raw_col,
        forward_col=forward_col,
        n_quantiles=int(eval_cfg.get("n_quantiles", 5)),
        rebalance_days=int(eval_cfg.get("rebalance_days", 5)),
        rolling_ic_window=int(eval_cfg.get("rolling_ic_window", 252)),
        min_cross_section_count=int(eval_cfg.get("min_cross_section_count", 30)),
    )
    in_sample_frame, oos_frame = _split_oos(frame, gate_cfg=config.get("gate", {}).get("library_decision_gate", {}))
    in_sample_metrics = compute_evaluation_metrics(
        in_sample_frame,
        factor_col=processed_col,
        direction_col="factor_value_for_eval",
        raw_factor_col=raw_col,
        forward_col=forward_col,
        n_quantiles=int(eval_cfg.get("n_quantiles", 5)),
        rebalance_days=int(eval_cfg.get("rebalance_days", 5)),
        rolling_ic_window=int(eval_cfg.get("rolling_ic_window", 252)),
        min_cross_section_count=int(eval_cfg.get("min_cross_section_count", 30)),
    )
    oos_metrics = compute_evaluation_metrics(
        oos_frame,
        factor_col=processed_col,
        direction_col="factor_value_for_eval",
        raw_factor_col=raw_col,
        forward_col=forward_col,
        n_quantiles=int(eval_cfg.get("n_quantiles", 5)),
        rebalance_days=int(eval_cfg.get("rebalance_days", 5)),
        rolling_ic_window=int(eval_cfg.get("rolling_ic_window", 252)),
        min_cross_section_count=int(eval_cfg.get("min_cross_section_count", 30)),
    )

    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_paths = _build_output_paths(output_root=Path(output_root), factor_id=factor_id, run_id=run_id)
    result = {
        "factor_id": factor_id,
        "factor_spec": spec,
        "direction": direction,
        "run_id": run_id,
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "primary_horizon": primary_horizon,
        "metrics": {"full_sample": full_metrics},
        "oos_evidence": {"in_sample": in_sample_metrics, "out_of_sample": oos_metrics},
        "baseline_comparison": {},
        "data_snapshot": _data_snapshot(frame, duckdb_path),
        "code_version": _code_version(registry_path=registry_path, universe_path=universe_path, evaluation_path=evaluation_path),
        "validity_checks": validity_checks,
        "output_paths": {k: str(v) for k, v in output_paths.items()},
    }
    result["baseline_comparison"] = compare_with_baselines(result, baseline_evidence, config.get("gate", {}).get("library_decision_gate"))
    result["gate_decision"] = apply_gate(result, config)

    if persist_json:
        _write_evaluation_result_json(result, output_paths["evaluation_result_json"])
    return sanitize_for_json(result)


def _resolve_factor_col(frame: pd.DataFrame, explicit: str | None, *, preferred: list[str]) -> str:
    if explicit:
        if explicit not in frame.columns:
            raise ValueError(f"missing factor column: {explicit}")
        return explicit
    for candidate in preferred:
        if candidate in frame.columns:
            return candidate
    raise ValueError(f"unable to infer factor column from candidates: {preferred}")


def _split_oos(frame: pd.DataFrame, *, gate_cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    simple_oos = gate_cfg.get("evidence", {}).get("simple_oos", {})
    in_sample_pct = float(simple_oos.get("in_sample_pct", 0.75))
    dates = sorted(frame["trade_date"].dropna().unique().tolist())
    if not dates:
        return frame.iloc[0:0].copy(), frame.iloc[0:0].copy()
    split_idx = max(1, min(len(dates) - 1, int(len(dates) * in_sample_pct)))
    split_date = dates[split_idx]
    return frame.loc[frame["trade_date"] < split_date].copy(), frame.loc[frame["trade_date"] >= split_date].copy()


def _build_output_paths(*, output_root: Path, factor_id: str, run_id: str) -> dict[str, Path]:
    return {
        "evaluation_result_json": output_root / "evaluation_results" / f"{factor_id}_{run_id}.json",
        "factor_library_json": output_root / "factor_library" / "factor_library.json",
        "report_markdown": Path("reports") / "factor_evaluation" / f"{factor_id}_{run_id}.md",
    }


def _data_snapshot(frame: pd.DataFrame, duckdb_path: str | Path | None) -> dict[str, Any]:
    snapshot = {
        "duckdb_path": str(duckdb_path) if duckdb_path else None,
        "sample_min_trade_date": frame["trade_date"].min().strftime("%Y-%m-%d") if not frame.empty else None,
        "sample_max_trade_date": frame["trade_date"].max().strftime("%Y-%m-%d") if not frame.empty else None,
        "sample_row_count": int(len(frame)),
    }
    if duckdb_path and Path(duckdb_path).exists():
        with duckdb.connect(str(duckdb_path), read_only=True) as con:
            row = con.execute(
                """
                SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
                FROM daily_panel
                """
            ).fetchone()
        snapshot.update(
            {
                "daily_panel_min_trade_date": str(row[0]) if row and row[0] is not None else None,
                "daily_panel_max_trade_date": str(row[1]) if row and row[1] is not None else None,
                "daily_panel_row_count": int(row[2]) if row else None,
            }
        )
    return sanitize_for_json(snapshot)


def _code_version(
    *,
    registry_path: str | Path | None,
    universe_path: str | Path | None,
    evaluation_path: str | Path | None,
) -> dict[str, Any]:
    commit = None
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        commit = None

    hashes = {}
    for name, path in {
        "registry": registry_path,
        "universe": universe_path,
        "evaluation": evaluation_path,
    }.items():
        if path and Path(path).exists():
            hashes[name] = hashlib.md5(Path(path).read_bytes()).hexdigest()
    return {"git_commit": commit, "config_hashes": hashes}


def _write_evaluation_result_json(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sanitize_for_json(result), ensure_ascii=False, indent=2), encoding="utf-8")
