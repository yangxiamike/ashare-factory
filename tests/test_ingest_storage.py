from pathlib import Path

import duckdb
import pandas as pd

from ashare_data.config import Settings
from ashare_data.storage import (
    has_raw_daily_partition,
    initialize_warehouse,
    record_ingest_status,
    upsert_trade_date_table,
    write_raw_partition,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        TUSHARE_TOKEN="test-token",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        raw_dir=tmp_path / "data" / "raw",
        warehouse_dir=tmp_path / "data" / "warehouse",
        report_dir=tmp_path / "reports" / "dq",
        duckdb_path=tmp_path / "data" / "warehouse" / "ashare.duckdb",
    )


def test_daily_raw_partition_path_and_detection(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    initialize_warehouse(settings)

    frame = pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260530", "open": 10.0}])
    path = write_raw_partition(settings, "daily", "20260530", frame)

    assert path == tmp_path / "data" / "raw" / "daily" / "trade_date=20260530" / "daily.parquet"
    assert has_raw_daily_partition(settings, "daily", "20260530")


def test_ingest_status_records_timestamps_and_payload(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    initialize_warehouse(settings)

    record_ingest_status(
        settings,
        endpoint="daily",
        trade_date="20260530",
        status="success",
        row_count=321,
        raw_path="data/raw/daily/trade_date=20260530/daily.parquet",
        error_message="",
        started_at="2026-05-31 10:00:00",
        finished_at="2026-05-31 10:00:03",
    )

    with duckdb.connect(str(settings.duckdb_path)) as con:
        row = con.execute(
            """
            SELECT endpoint, trade_date, status, row_count, raw_path, started_at, finished_at
            FROM ingest_status
            WHERE endpoint='daily' AND trade_date='20260530'
            """
        ).fetchone()
    assert row is not None
    assert row[0] == "daily"
    assert row[1] == "20260530"
    assert row[2] == "success"
    assert row[3] == 321
    assert "trade_date=20260530" in row[4]
    assert row[5] is not None
    assert row[6] is not None


def test_upsert_trade_date_table_is_idempotent_on_trade_date_ts_code(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    initialize_warehouse(settings)

    first = pd.DataFrame(
        [{"ts_code": "000001.SZ", "trade_date": "20260530", "open": 10.0, "close": 10.2}]
    )
    second = pd.DataFrame(
        [{"ts_code": "000001.SZ", "trade_date": "20260530", "open": 12.0, "close": 12.2}]
    )

    upsert_trade_date_table(settings, "daily", "20260530", first)
    upsert_trade_date_table(settings, "daily", "20260530", second)

    with duckdb.connect(str(settings.duckdb_path)) as con:
        rows = con.execute(
            "SELECT ts_code, trade_date, open, close FROM daily WHERE trade_date='20260530'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][2] == 12.0
