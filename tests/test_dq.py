from pathlib import Path

import duckdb

from ashare_data.dq import build_settings_for_path, run_quality_checks


def _prepare_database(db_path: Path) -> None:
    with duckdb.connect(str(db_path)) as con:
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
                turnover_rate DOUBLE,
                pe DOUBLE,
                pb DOUBLE,
                total_mv DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_basic VALUES
            ('000001.SZ', '20240506', 1.2, 10, 1.5, 100000),
            ('000001.SZ', '20240507', NULL, 10.5, 1.6, 101000),
            ('000003.SZ', '20240507', 0.9, 9, 1.1, 50000)
            """
        )
        con.execute(
            """
            CREATE TABLE stock_industry_history (
                ts_code VARCHAR,
                industry_name VARCHAR,
                in_date VARCHAR,
                out_date VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO stock_industry_history VALUES
            ('000001.SZ', 'Bank', '20200101', NULL)
            """
        )


def test_run_quality_checks_writes_markdown_report(tmp_path: Path) -> None:
    db_path = tmp_path / "warehouse.duckdb"
    report_root = tmp_path / "reports"
    _prepare_database(db_path)

    settings = build_settings_for_path(db_path, report_root)
    report_path = run_quality_checks(settings, expected_trade_dates=["20240506", "20240507"])

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "A股日频数据底座一期质检报告" in content
    assert "WARN 关键字段缺失率" in content
    assert "FAIL OHLC 合理性检查" in content
    assert "WARN daily 与 daily_basic 覆盖差异" in content
    assert "WARN 申万历史行业归属匹配率" in content
    assert "`20240506, 20240507`" in content
    assert "`daily_basic.turnover_rate`=33.33%" in content


def test_date_coverage_flags_missing_expected_trade_date(tmp_path: Path) -> None:
    db_path = tmp_path / "warehouse.duckdb"
    _prepare_database(db_path)

    settings = build_settings_for_path(db_path, tmp_path)
    report_path = run_quality_checks(settings, expected_trade_dates=["20240506", "20240508"])

    content = report_path.read_text(encoding="utf-8")
    assert "FAIL 日期覆盖检查" in content
    assert "20240508" in content


def test_report_defaults_to_duckdb_sibling_reports_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "warehouse.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _prepare_database(db_path)

    settings = build_settings_for_path(db_path)
    report_path = run_quality_checks(settings)

    assert report_path.parent == db_path.parent / "reports" / "dq"


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

    report_path = run_quality_checks(build_settings_for_path(db_path, tmp_path))
    content = report_path.read_text(encoding="utf-8")

    assert "FAIL 主键重复检查" in content
    assert "发现重复主键: `daily`=1" in content


def test_missing_rates_include_daily_basic_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "warehouse.duckdb"
    _prepare_database(db_path)

    report_path = run_quality_checks(build_settings_for_path(db_path, tmp_path))
    content = report_path.read_text(encoding="utf-8")

    assert "WARN 关键字段缺失率" in content
    assert "- `daily_basic.turnover_rate`: missing `1/3`, rate `33.33%`" in content
