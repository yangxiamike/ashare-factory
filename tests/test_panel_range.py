from pathlib import Path

import pandas as pd

from ashare_data.config import Settings
from ashare_data.panel import build_daily_panel
from ashare_data.storage import connect, initialize_warehouse, replace_table


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


def _seed_minimal_tables(settings: Settings) -> None:
    replace_table(
        settings,
        "stock_basic",
        pd.DataFrame([{"ts_code": "000001.SZ", "name": "Ping An Bank", "market": "Main"}]),
    )
    replace_table(
        settings,
        "daily",
        pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20260524", "open": 10.0, "close": 10.5},
                {"ts_code": "000001.SZ", "trade_date": "20260525", "open": 10.1, "close": 10.6},
            ]
        ),
    )
    replace_table(settings, "adj_factor", pd.DataFrame())
    replace_table(settings, "daily_basic", pd.DataFrame())
    replace_table(settings, "stk_limit", pd.DataFrame())
    replace_table(settings, "suspend_d", pd.DataFrame())
    replace_table(settings, "index_classify", pd.DataFrame())
    replace_table(settings, "index_member_all", pd.DataFrame())


def test_build_panel_range_delete_then_insert(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    initialize_warehouse(settings)
    _seed_minimal_tables(settings)

    assert build_daily_panel(settings) == 2
    assert build_daily_panel(settings, start_date="20260525", end_date="20260525") == 1

    with connect(settings) as con:
        cnt = con.execute(
            "SELECT COUNT(*) FROM daily_panel WHERE ts_code='000001.SZ' AND trade_date='20260525'"
        ).fetchone()[0]
    assert cnt == 1


def test_build_panel_range_requires_both_dates(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    initialize_warehouse(settings)
    _seed_minimal_tables(settings)

    try:
        build_daily_panel(settings, start_date="20260525")
    except ValueError as exc:
        assert "provided together" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing end_date")
