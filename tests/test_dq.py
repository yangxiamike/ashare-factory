from pathlib import Path

import duckdb

from ashare_data.config import Settings
from ashare_data.dq import run_quality_checks


def _settings(tmp_path: Path, db_path: Path) -> Settings:
    return Settings(
        TUSHARE_TOKEN="test-token",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        raw_dir=tmp_path / "data" / "raw",
        warehouse_dir=db_path.parent,
        report_dir=tmp_path / "reports" / "dq",
        duckdb_path=db_path,
    )


def _prepare_database(db_path: Path) -> None:
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE trade_cal (
                exchange VARCHAR,
                cal_date VARCHAR,
                is_open VARCHAR,
                pretrade_date VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO trade_cal VALUES
            ('SSE', '20240506', '1', NULL),
            ('SSE', '20240507', '1', '20240506')
            """
        )
        con.execute(
            """
            CREATE TABLE daily (
                ts_code VARCHAR,
                trade_date VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                vol DOUBLE,
                amount DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily VALUES
            ('000001.SZ', '20240506', 10, 11, 9, 10.5, 1000, 2000),
            ('000002.SZ', '20240506', 8, 7, 7.5, 7.8, 900, 1500),
            ('000001.SZ', '20240507', 10.5, 10.8, 10.1, 10.2, 1100, 2100)
            """
        )
        con.execute(
            """
            CREATE TABLE daily_basic (
                ts_code VARCHAR,
                trade_date VARCHAR,
                close DOUBLE,
                turnover_rate DOUBLE,
                total_mv DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_basic VALUES
            ('000001.SZ', '20240506', 10.5, 1.2, 100000),
            ('000001.SZ', '20240507', 10.2, NULL, 101000),
            ('000003.SZ', '20240507', 9.0, 0.9, 50000)
            """
        )
        con.execute(
            """
            CREATE TABLE daily_panel (
                ts_code VARCHAR,
                trade_date VARCHAR,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                amount DOUBLE,
                turnover_rate DOUBLE,
                total_mv DOUBLE,
                sw_l1_code VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_panel VALUES
            ('000001.SZ', '20240506', 10, 11, 9, 10.5, 2000, 1.2, 100000, '801780.SI'),
            ('000002.SZ', '20240506', 8, 7, 7.5, 7.8, 1500, 0.8, 90000, NULL),
            ('000001.SZ', '20240507', 10.5, 10.8, 10.1, 10.2, 2100, NULL, 101000, '801780.SI')
            """
        )
        con.execute(
            """
            CREATE TABLE ingest_status (
                endpoint VARCHAR,
                trade_date VARCHAR,
                status VARCHAR,
                row_count BIGINT,
                raw_path VARCHAR,
                error_message VARCHAR,
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            )
            """
        )
        con.execute(
            """
            INSERT INTO ingest_status VALUES
            ('daily', '20240506', 'success', 2, 'raw', '', current_timestamp, current_timestamp),
            ('daily', '20240507', 'success', 1, 'raw', '', current_timestamp, current_timestamp),
            ('daily_basic', '20240506', 'success', 1, 'raw', '', current_timestamp, current_timestamp),
            ('daily_basic', '20240507', 'failed', 0, '', 'boom', current_timestamp, current_timestamp)
            """
        )


def test_run_quality_checks_writes_history_report(tmp_path: Path) -> None:
    db_path = tmp_path / "warehouse.duckdb"
    _prepare_database(db_path)

    report_path = run_quality_checks(
        _settings(tmp_path, db_path),
        start_date="20240506",
        end_date="20240507",
    )

    assert report_path.name.startswith("history_dq_20240506_20240507_")
    content = report_path.read_text(encoding="utf-8")
    assert "A股日频历史补数质检报告" in content
    assert "WARN 历史采集状态" in content
    assert "FAIL OHLC 合理性检查" in content
    assert "WARN 关键字段缺失率" in content
    assert "WARN daily 与 daily_basic 覆盖差异" in content
    assert "WARN 申万历史行业归属匹配率" in content
    assert "预期交易日数量: `2`" in content


def test_history_report_contains_all_required_sections(tmp_path: Path) -> None:
    db_path = tmp_path / "warehouse.duckdb"
    _prepare_database(db_path)

    report_path = run_quality_checks(
        _settings(tmp_path, db_path),
        start_date="20240506",
        end_date="20240507",
    )

    content = report_path.read_text(encoding="utf-8")
    required_sections = [
        "历史采集状态",
        "日期覆盖检查",
        "主键重复检查",
        "关键字段缺失率",
        "OHLC 合理性检查",
        "daily 与 daily_basic 覆盖差异",
        "申万历史行业归属匹配率",
    ]

    for section in required_sections:
        assert section in content


def test_date_coverage_flags_missing_expected_trade_date(tmp_path: Path) -> None:
    db_path = tmp_path / "warehouse.duckdb"
    _prepare_database(db_path)

    report_path = run_quality_checks(
        _settings(tmp_path, db_path),
        expected_trade_dates=["20240506", "20240508"],
    )

    content = report_path.read_text(encoding="utf-8")
    assert "FAIL 日期覆盖检查" in content
    assert "20240508" in content


def test_report_defaults_to_duckdb_sibling_reports_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "warehouse.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _prepare_database(db_path)

    report_path = run_quality_checks(_settings(tmp_path, db_path))

    assert report_path.parent == tmp_path / "reports" / "dq"


def test_primary_key_duplicate_check_flags_duplicate_groups(tmp_path: Path) -> None:
    db_path = tmp_path / "warehouse.duckdb"
    _prepare_database(db_path)
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            INSERT INTO daily VALUES
            ('000001.SZ', '20240506', 10.1, 11.2, 9.1, 10.6, 1001, 2001)
            """
        )

    report_path = run_quality_checks(_settings(tmp_path, db_path))
    content = report_path.read_text(encoding="utf-8")

    assert "FAIL 主键重复检查" in content
    assert "发现重复主键: `daily`=1" in content
