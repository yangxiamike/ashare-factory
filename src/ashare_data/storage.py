from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ashare_data.config import Settings


EXPECTED_COLUMNS: dict[str, list[str]] = {
    "trade_cal": ["exchange", "cal_date", "is_open", "pretrade_date"],
    "stock_basic": [
        "ts_code",
        "symbol",
        "name",
        "area",
        "industry",
        "market",
        "list_date",
        "act_name",
        "act_ent_type",
    ],
    "daily": [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ],
    "adj_factor": ["ts_code", "trade_date", "adj_factor"],
    "daily_basic": [
        "ts_code",
        "trade_date",
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
    ],
    "suspend_d": ["ts_code", "trade_date", "suspend_type", "suspend_timing"],
    "stk_limit": ["ts_code", "trade_date", "up_limit", "down_limit"],
    "index_classify": ["index_code", "industry_name", "level", "industry_code", "src"],
    "index_member_all": [
        "l1_code",
        "l1_name",
        "l2_code",
        "l2_name",
        "l3_code",
        "l3_name",
        "ts_code",
        "con_code",
        "con_name",
        "in_date",
        "out_date",
        "is_new",
    ],
}


def resolved(settings: Settings) -> Settings:
    return settings.resolve_paths()


def connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    settings = resolved(settings)
    settings.warehouse_dir.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(settings.duckdb_path))


def initialize_warehouse(settings: Settings) -> None:
    settings = resolved(settings)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    settings.warehouse_dir.mkdir(parents=True, exist_ok=True)
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    with connect(settings) as con:
        sql_path = settings.sql_dir / "create_tables.sql"
        con.execute(sql_path.read_text(encoding="utf-8"))
        _migrate_warehouse_schema(con)


def normalize_frame(endpoint: str, frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in EXPECTED_COLUMNS.get(endpoint, []):
        if column not in frame.columns:
            frame[column] = pd.NA
    for column in TEXT_COLUMNS.get(endpoint, []):
        if column in frame.columns:
            frame[column] = frame[column].astype("string")
    return frame


TEXT_COLUMNS: dict[str, list[str]] = {
    "trade_cal": ["exchange", "cal_date", "is_open", "pretrade_date"],
    "stock_basic": [
        "ts_code",
        "symbol",
        "name",
        "area",
        "industry",
        "market",
        "list_date",
        "act_name",
        "act_ent_type",
    ],
    "daily": ["ts_code", "trade_date"],
    "adj_factor": ["ts_code", "trade_date"],
    "daily_basic": ["ts_code", "trade_date"],
    "suspend_d": ["ts_code", "trade_date", "suspend_type", "suspend_timing"],
    "stk_limit": ["ts_code", "trade_date"],
    "index_classify": ["index_code", "industry_name", "level", "industry_code", "src"],
    "index_member_all": [
        "l1_code",
        "l1_name",
        "l2_code",
        "l2_name",
        "l3_code",
        "l3_name",
        "ts_code",
        "con_code",
        "con_name",
        "in_date",
        "out_date",
        "is_new",
    ],
}


def _migrate_warehouse_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Keep old DuckDB files compatible with the current expected schema."""
    for table_name, columns in TEXT_COLUMNS.items():
        existing = {
            row[0]
            for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = ?
                """,
                [table_name],
            ).fetchall()
        }
        for column in columns:
            if column in existing:
                con.execute(f"ALTER TABLE {table_name} ALTER COLUMN {column} TYPE VARCHAR")


def write_raw(settings: Settings, endpoint: str, frame: pd.DataFrame) -> Path:
    settings = resolved(settings)
    endpoint_dir = settings.raw_dir / endpoint
    endpoint_dir.mkdir(parents=True, exist_ok=True)
    path = endpoint_dir / f"{endpoint}.parquet"
    normalize_frame(endpoint, frame).to_parquet(path, index=False)
    return path


def raw_partition_path(settings: Settings, endpoint: str, trade_date: str) -> Path:
    settings = resolved(settings)
    return settings.raw_dir / endpoint / f"trade_date={trade_date}" / f"{endpoint}.parquet"


def write_raw_partition(settings: Settings, endpoint: str, trade_date: str, frame: pd.DataFrame) -> Path:
    path = raw_partition_path(settings, endpoint, trade_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalize_frame(endpoint, frame).to_parquet(path, index=False)
    return path


def has_raw_daily_partition(settings: Settings, endpoint: str, trade_date: str) -> bool:
    return raw_partition_path(settings, endpoint, trade_date).exists()


def replace_table(settings: Settings, table_name: str, frame: pd.DataFrame) -> int:
    frame = normalize_frame(table_name, frame)
    with connect(settings) as con:
        con.register("_frame", frame)
        con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM _frame")
        con.unregister("_frame")
    return len(frame)


def upsert_trade_cal_table(settings: Settings, frame: pd.DataFrame) -> int:
    frame = normalize_frame("trade_cal", frame)
    if frame.empty:
        return 0
    with connect(settings) as con:
        con.register("_frame", frame)
        con.execute("DELETE FROM trade_cal WHERE cal_date IN (SELECT cal_date FROM _frame)")
        con.execute("INSERT INTO trade_cal SELECT * FROM _frame")
        con.unregister("_frame")
    return len(frame)


def upsert_trade_date_table(
    settings: Settings, table_name: str, trade_date: str, frame: pd.DataFrame
) -> int:
    frame = normalize_frame(table_name, frame)
    with connect(settings) as con:
        con.execute(f"DELETE FROM {table_name} WHERE trade_date = ?", [trade_date])
        if frame.empty:
            return 0
        con.register("_frame", frame)
        con.execute(f"INSERT INTO {table_name} SELECT * FROM _frame")
        con.unregister("_frame")
    return len(frame)


def record_ingest_status(
    settings: Settings,
    endpoint: str,
    trade_date: str,
    status: str,
    row_count: int = 0,
    raw_path: str | Path | None = None,
    error_message: str = "",
    started_at: str | None = None,
    finished_at: str | None = None,
) -> None:
    with connect(settings) as con:
        con.execute(
            """
            DELETE FROM ingest_status
            WHERE endpoint = ? AND trade_date = ?
            """,
            [endpoint, trade_date],
        )
        con.execute(
            """
            INSERT INTO ingest_status
            VALUES (
                ?, ?, ?, ?, ?, ?,
                CASE WHEN ? IS NULL THEN current_timestamp ELSE CAST(? AS TIMESTAMP) END,
                CASE WHEN ? IS NULL THEN current_timestamp ELSE CAST(? AS TIMESTAMP) END
            )
            """,
            [
                endpoint,
                trade_date,
                status,
                row_count,
                str(raw_path or ""),
                error_message,
                started_at,
                started_at,
                finished_at,
                finished_at,
            ],
        )


def has_successful_ingest(settings: Settings, endpoint: str, trade_date: str) -> bool:
    with connect(settings) as con:
        row = con.execute(
            """
            SELECT raw_path
            FROM ingest_status
            WHERE endpoint = ? AND trade_date = ? AND status = 'success'
            """,
            [endpoint, trade_date],
        ).fetchone()
    return bool(row and row[0] and Path(row[0]).exists())


def load_raw_table(settings: Settings, endpoint: str) -> int:
    settings = resolved(settings)
    path = settings.raw_dir / endpoint / f"{endpoint}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Raw parquet not found for {endpoint}: {path}")
    frame = pd.read_parquet(path)
    return replace_table(settings, endpoint, frame)
