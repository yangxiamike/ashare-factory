from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Sequence

import duckdb
import pandas as pd

from ashare_data.config import Settings


DAILY_PANEL_REQUIRED_COLUMNS: tuple[str, ...] = (
    "trade_date",
    "ts_code",
    "pct_chg",
    "close",
    "pre_close",
    "amount",
    "total_mv",
    "pe_ttm",
    "pb",
    "turnover_rate",
    "dv_ratio",
    "sw_l1_name",
    "is_suspended",
    "up_limit",
    "down_limit",
)


def resolve_settings(settings: Settings | None = None) -> Settings:
    return (settings or Settings()).resolve_paths()


def _validate_trade_date(trade_date: str) -> None:
    try:
        datetime.strptime(trade_date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"trade_date must be YYYYMMDD, got: {trade_date}") from exc


def _connect_readonly(settings: Settings) -> duckdb.DuckDBPyConnection:
    duckdb_path = Path(settings.duckdb_path)
    if not duckdb_path.exists():
        raise FileNotFoundError(f"DuckDB file not found: {duckdb_path}")
    return duckdb.connect(str(duckdb_path), read_only=True)


def validate_daily_panel_columns(
    settings: Settings | None = None,
    required_columns: Sequence[str] = DAILY_PANEL_REQUIRED_COLUMNS,
) -> list[str]:
    resolved = resolve_settings(settings)
    with _connect_readonly(resolved) as con:
        rows = con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = 'daily_panel'
            ORDER BY ordinal_position
            """
        ).fetchall()
    existing = {row[0] for row in rows}
    missing = [column for column in required_columns if column not in existing]
    if missing:
        raise ValueError(f"daily_panel missing required columns: {', '.join(missing)}")
    return [row[0] for row in rows]


def daily_panel_coverage(settings: Settings | None = None) -> dict[str, int | str]:
    resolved = resolve_settings(settings)
    validate_daily_panel_columns(resolved)
    with _connect_readonly(resolved) as con:
        min_trade_date, max_trade_date, row_count = con.execute(
            "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM daily_panel"
        ).fetchone()
    return {
        "duckdb_path": str(resolved.duckdb_path),
        "min_trade_date": min_trade_date,
        "max_trade_date": max_trade_date,
        "row_count": int(row_count),
    }


def load_daily_panel(
    trade_date: str,
    settings: Settings | None = None,
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    _validate_trade_date(trade_date)
    resolved = resolve_settings(settings)
    validated_columns = validate_daily_panel_columns(resolved)
    selected_columns = list(columns or validated_columns)
    missing = [column for column in selected_columns if column not in validated_columns]
    if missing:
        raise ValueError(f"requested columns not found in daily_panel: {', '.join(missing)}")
    query = f"""
        SELECT {", ".join(selected_columns)}
        FROM daily_panel
        WHERE trade_date = ?
    """
    with _connect_readonly(resolved) as con:
        return con.execute(query, [trade_date]).df()


def load_daily_panel_window(
    trade_date: str,
    lookback_days: int = 5,
    settings: Settings | None = None,
    columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    _validate_trade_date(trade_date)
    if lookback_days < 1:
        raise ValueError(f"lookback_days must be >= 1, got: {lookback_days}")
    resolved = resolve_settings(settings)
    validated_columns = validate_daily_panel_columns(resolved)
    selected_columns = list(columns or validated_columns)
    missing = [column for column in selected_columns if column not in validated_columns]
    if missing:
        raise ValueError(f"requested columns not found in daily_panel: {', '.join(missing)}")
    query = f"""
        WITH recent_dates AS (
            SELECT trade_date
            FROM daily_panel
            WHERE trade_date <= ?
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT ?
        )
        SELECT {", ".join(selected_columns)}
        FROM daily_panel
        WHERE trade_date IN (SELECT trade_date FROM recent_dates)
    """
    with _connect_readonly(resolved) as con:
        return con.execute(query, [trade_date, lookback_days]).df()
