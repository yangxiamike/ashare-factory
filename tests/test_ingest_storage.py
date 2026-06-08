from pathlib import Path

import duckdb
import pandas as pd

from ashare_data.config import Settings
from ashare_data.storage import (
    has_raw_daily_partition,
    initialize_warehouse,
    record_ingest_status,
    upsert_index_weight_table,
    upsert_trade_date_table,
    write_raw_index_partition,
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


def test_index_weight_raw_partition_and_upsert_preserve_other_indexes(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    initialize_warehouse(settings)

    hs300_first = pd.DataFrame(
        [{"index_code": "000300.SH", "con_code": "000001.SZ", "trade_date": "20260530", "weight": 3.1}]
    )
    hs300_second = pd.DataFrame(
        [{"index_code": "000300.SH", "con_code": "000001.SZ", "trade_date": "20260530", "weight": 3.3}]
    )
    zz500 = pd.DataFrame(
        [{"index_code": "000905.SH", "con_code": "000002.SZ", "trade_date": "20260530", "weight": 1.8}]
    )

    path = write_raw_index_partition(settings, "index_weight", "000300.SH", "20260530", hs300_first)
    upsert_index_weight_table(settings, "000300.SH", "20260530", hs300_first)
    upsert_index_weight_table(settings, "000905.SH", "20260530", zz500)
    upsert_index_weight_table(settings, "000300.SH", "20260530", hs300_second)

    assert path == (
        tmp_path
        / "data"
        / "raw"
        / "index_weight"
        / "index_code=000300.SH"
        / "trade_date=20260530"
        / "index_weight.parquet"
    )

    with duckdb.connect(str(settings.duckdb_path)) as con:
        rows = con.execute(
            """
            SELECT index_code, con_code, trade_date, weight
            FROM index_weight
            ORDER BY index_code, con_code
            """
        ).fetchall()

    assert rows == [
        ("000300.SH", "000001.SZ", "20260530", 3.3),
        ("000905.SH", "000002.SZ", "20260530", 1.8),
    ]


def test_initialize_warehouse_adds_new_stock_basic_columns_to_existing_duckdb(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.warehouse_dir.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(settings.duckdb_path)) as con:
        con.execute(
            """
            CREATE TABLE stock_basic (
                ts_code VARCHAR,
                symbol VARCHAR,
                name VARCHAR,
                area VARCHAR,
                industry VARCHAR,
                market VARCHAR,
                list_date VARCHAR,
                act_name VARCHAR,
                act_ent_type VARCHAR
            )
            """
        )

    initialize_warehouse(settings)

    with duckdb.connect(str(settings.duckdb_path)) as con:
        columns = {
            row[0]
            for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = 'stock_basic'
                """
            ).fetchall()
        }

    assert "list_status" in columns
    assert "delist_date" in columns
