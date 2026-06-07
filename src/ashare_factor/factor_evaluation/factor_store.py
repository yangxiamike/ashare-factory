from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import duckdb
import pandas as pd


@contextmanager
def _open_connection(con_or_path: duckdb.DuckDBPyConnection | str | Path) -> Iterator[duckdb.DuckDBPyConnection]:
    if isinstance(con_or_path, duckdb.DuckDBPyConnection):
        yield con_or_path
        return
    con = duckdb.connect(str(con_or_path))
    try:
        yield con
    finally:
        con.close()


def write_factor_values(con_or_path: duckdb.DuckDBPyConnection | str | Path, factor_df: pd.DataFrame) -> None:
    if factor_df.empty:
        return
    payload = factor_df.loc[:, ["trade_date", "ts_code", "factor_id", "factor_value_raw", "factor_value_processed"]].copy()
    payload["trade_date"] = pd.to_datetime(payload["trade_date"]).dt.date
    payload = payload.rename(
        columns={
            "factor_value_raw": "value_raw",
            "factor_value_processed": "value_processed",
        }
    )
    with _open_connection(con_or_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS factor_values (
                trade_date DATE NOT NULL,
                ts_code VARCHAR NOT NULL,
                factor_id VARCHAR NOT NULL,
                value_raw DOUBLE,
                value_processed DOUBLE,
                PRIMARY KEY (trade_date, ts_code, factor_id)
            )
            """
        )
        con.register("_factor_values_stage", payload)
        con.execute("INSERT OR REPLACE INTO factor_values SELECT * FROM _factor_values_stage")
        con.unregister("_factor_values_stage")


def read_factor_values(
    con_or_path: duckdb.DuckDBPyConnection | str | Path,
    *,
    factor_ids: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    clauses: list[str] = ["1 = 1"]
    params: list[Any] = []
    if factor_ids:
        placeholders = ", ".join(["?"] * len(factor_ids))
        clauses.append(f"factor_id IN ({placeholders})")
        params.extend(factor_ids)
    if start:
        clauses.append("trade_date >= ?")
        params.append(start)
    if end:
        clauses.append("trade_date <= ?")
        params.append(end)
    with _open_connection(con_or_path) as con:
        return con.execute(
            f"""
            SELECT trade_date, ts_code, factor_id, value_raw, value_processed
            FROM factor_values
            WHERE {' AND '.join(clauses)}
            ORDER BY trade_date, ts_code, factor_id
            """,
            params,
        ).fetchdf()


def write_evaluation_artifacts(
    con_or_path: duckdb.DuckDBPyConnection | str | Path,
    result: dict[str, Any],
) -> None:
    with _open_connection(con_or_path) as con:
        _create_evaluation_tables(con)
        _upsert_one(con, "evaluation_runs", pd.DataFrame([_evaluation_run_row(result)]))
        _upsert_one(con, "evaluation_metrics", pd.DataFrame([_evaluation_metric_row(result)]))
        quantiles = _evaluation_quantile_rows(result)
        if quantiles:
            _upsert_one(con, "evaluation_quantiles", pd.DataFrame(quantiles))
        _upsert_one(con, "evaluation_period_metrics", pd.DataFrame(_evaluation_period_rows(result)))


def _create_evaluation_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS evaluation_runs (
            run_id VARCHAR PRIMARY KEY,
            factor_id VARCHAR NOT NULL,
            evaluated_at TIMESTAMP NOT NULL,
            status VARCHAR NOT NULL,
            git_commit VARCHAR,
            data_start_date DATE,
            data_end_date DATE,
            sample_row_count INTEGER,
            primary_horizon INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS evaluation_metrics (
            run_id VARCHAR PRIMARY KEY,
            factor_id VARCHAR NOT NULL,
            coverage_pct DOUBLE,
            n_valid_dates INTEGER,
            rank_ic_mean DOUBLE,
            rank_ic_std DOUBLE,
            rank_ic_ir DOUBLE,
            rank_ic_t_stat DOUBLE,
            rank_ic_win_rate DOUBLE,
            rank_ic_skew DOUBLE,
            rank_ic_kurtosis DOUBLE,
            q5_q1_spread_mean DOUBLE,
            top_quantile_return DOUBLE,
            top_quantile_sharpe DOUBLE,
            top_quantile_max_dd DOUBLE,
            top_quantile_calmar DOUBLE,
            long_short_sharpe DOUBLE,
            mean_turnover DOUBLE,
            turnover_std DOUBLE,
            ic_half_life_lag INTEGER
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS evaluation_quantiles (
            run_id VARCHAR NOT NULL,
            factor_id VARCHAR NOT NULL,
            quantile INTEGER NOT NULL,
            mean_return DOUBLE,
            hit_rate DOUBLE,
            PRIMARY KEY (run_id, quantile)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS evaluation_period_metrics (
            run_id VARCHAR NOT NULL,
            factor_id VARCHAR NOT NULL,
            period VARCHAR NOT NULL,
            rank_ic_mean DOUBLE,
            rank_ic_ir DOUBLE,
            q5_q1_spread_mean DOUBLE,
            top_quantile_return DOUBLE,
            top_quantile_sharpe DOUBLE,
            top_quantile_max_dd DOUBLE,
            mean_turnover DOUBLE,
            PRIMARY KEY (run_id, period)
        )
        """
    )


def _upsert_one(con: duckdb.DuckDBPyConnection, table_name: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    stage_name = f"_{table_name}_stage"
    con.register(stage_name, frame)
    con.execute(f"INSERT OR REPLACE INTO {table_name} SELECT * FROM {stage_name}")
    con.unregister(stage_name)


def _evaluation_run_row(result: dict[str, Any]) -> dict[str, Any]:
    snapshot = result.get("data_snapshot", {})
    return {
        "run_id": result.get("run_id"),
        "factor_id": result.get("factor_id"),
        "evaluated_at": result.get("evaluated_at"),
        "status": result.get("gate_decision", {}).get("status") or result.get("status") or "candidate",
        "git_commit": result.get("code_version", {}).get("git_commit"),
        "data_start_date": snapshot.get("sample_min_trade_date"),
        "data_end_date": snapshot.get("sample_max_trade_date"),
        "sample_row_count": snapshot.get("sample_row_count"),
        "primary_horizon": result.get("primary_horizon"),
    }


def _evaluation_metric_row(result: dict[str, Any]) -> dict[str, Any]:
    full = result.get("metrics", {}).get("full_sample", {})
    rank_ic = full.get("rank_ic", {})
    quantile = full.get("quantile", {})
    top = full.get("top_quantile", {})
    long_short = full.get("long_short", {})
    turnover = full.get("turnover", {})
    stability = full.get("stability", {})
    return {
        "run_id": result.get("run_id"),
        "factor_id": result.get("factor_id"),
        "coverage_pct": full.get("coverage_pct"),
        "n_valid_dates": full.get("n_valid_dates"),
        "rank_ic_mean": rank_ic.get("mean"),
        "rank_ic_std": rank_ic.get("std"),
        "rank_ic_ir": rank_ic.get("ir"),
        "rank_ic_t_stat": rank_ic.get("t_stat"),
        "rank_ic_win_rate": rank_ic.get("win_rate"),
        "rank_ic_skew": rank_ic.get("skew"),
        "rank_ic_kurtosis": rank_ic.get("kurtosis"),
        "q5_q1_spread_mean": quantile.get("q5_q1_spread_mean"),
        "top_quantile_return": top.get("mean_return"),
        "top_quantile_sharpe": top.get("sharpe"),
        "top_quantile_max_dd": top.get("max_drawdown"),
        "top_quantile_calmar": top.get("calmar"),
        "long_short_sharpe": long_short.get("sharpe"),
        "mean_turnover": turnover.get("mean_turnover"),
        "turnover_std": turnover.get("turnover_std"),
        "ic_half_life_lag": stability.get("ic_half_life_lag"),
    }


def _evaluation_quantile_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    summary = result.get("metrics", {}).get("full_sample", {}).get("quantile", {}).get("summary", [])
    rows: list[dict[str, Any]] = []
    for entry in summary:
        rows.append(
            {
                "run_id": result.get("run_id"),
                "factor_id": result.get("factor_id"),
                "quantile": entry.get("quantile"),
                "mean_return": entry.get("mean_return"),
                "hit_rate": entry.get("hit_rate"),
            }
        )
    return rows


def _evaluation_period_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    mapping = {
        "full_sample": result.get("metrics", {}).get("full_sample", {}),
        "in_sample": result.get("oos_evidence", {}).get("in_sample", {}),
        "out_of_sample": result.get("oos_evidence", {}).get("out_of_sample", {}),
    }
    for period, payload in mapping.items():
        rank_ic = payload.get("rank_ic", {})
        quantile = payload.get("quantile", {})
        top = payload.get("top_quantile", {})
        turnover = payload.get("turnover", {})
        rows.append(
            {
                "run_id": result.get("run_id"),
                "factor_id": result.get("factor_id"),
                "period": period,
                "rank_ic_mean": rank_ic.get("mean"),
                "rank_ic_ir": rank_ic.get("ir"),
                "q5_q1_spread_mean": quantile.get("q5_q1_spread_mean"),
                "top_quantile_return": top.get("mean_return"),
                "top_quantile_sharpe": top.get("sharpe"),
                "top_quantile_max_dd": top.get("max_drawdown"),
                "mean_turnover": turnover.get("mean_turnover"),
            }
        )
    return rows
