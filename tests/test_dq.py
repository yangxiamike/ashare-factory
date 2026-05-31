from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from ashare_data.dq import build_settings_for_path, run_quality_checks


def _prepare_database(db_path: Path) -> None:
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            create table daily (
                ts_code varchar,
                trade_date varchar,
                open double,
                high double,
                low double,
                close double,
                vol double,
                amount double
            )
            """
        )
        con.execute(
            """
            insert into daily values
            ('000001.SZ', '20240506', 10, 11, 9, 10.5, 1000, 2000),
            ('000002.SZ', '20240506', 8, 7, 7.5, 7.8, 900, 1500),
            ('000001.SZ', '20240507', 10.5, 10.8, 10.1, 10.2, 1100, 2100)
            """
        )

        con.execute(
            """
            create table daily_basic (
                ts_code varchar,
                trade_date varchar,
                turnover_rate double,
                pe double,
                pb double,
                total_mv double
            )
            """
        )
        con.execute(
            """
            insert into daily_basic values
            ('000001.SZ', '20240506', 1.2, 10, 1.5, 100000),
            ('000001.SZ', '20240507', null, 10.5, 1.6, 101000),
            ('000003.SZ', '20240507', 0.9, 9, 1.1, 50000)
            """
        )

        con.execute(
            """
            create table stock_industry_history (
                ts_code varchar,
                industry_name varchar,
                in_date varchar,
                out_date varchar
            )
            """
        )
        con.execute(
            """
            insert into stock_industry_history values
            ('000001.SZ', 'Bank', '20200101', null)
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
    assert "A-share Data Quality Report" in content
    assert "FAIL OHLC 合理性检查" in content
    assert "WARN daily 与 daily_basic 覆盖差异" in content
    assert "WARN 行业历史归属匹配率" in content
    assert "`20240506, 20240507`" in content


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
