from pathlib import Path

import pandas as pd

from ashare_data.config import Settings
from ashare_data.dq import run_quality_checks
from ashare_data.panel import build_daily_panel
from ashare_data.storage import initialize_warehouse, replace_table


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


def test_build_daily_panel_matches_historical_industry(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    initialize_warehouse(settings)

    replace_table(
        settings,
        "trade_cal",
        pd.DataFrame(
            [{"exchange": "SSE", "cal_date": "20260525", "is_open": "1", "pretrade_date": None}]
        ),
    )
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
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260525",
                    "open": 10.0,
                    "high": 11.0,
                    "low": 9.5,
                    "close": 10.5,
                    "amount": 1000.0,
                }
            ]
        ),
    )
    replace_table(
        settings,
        "adj_factor",
        pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": "20260525", "adj_factor": 1.2}]),
    )
    replace_table(
        settings,
        "daily_basic",
        pd.DataFrame(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260525",
                    "turnover_rate": 0.8,
                    "total_mv": 100000.0,
                }
            ]
        ),
    )
    replace_table(settings, "stk_limit", pd.DataFrame())
    replace_table(settings, "suspend_d", pd.DataFrame())
    replace_table(settings, "index_classify", pd.DataFrame())
    replace_table(
        settings,
        "index_member_all",
        pd.DataFrame(
            [
                {
                    "con_code": "000001.SZ",
                    "con_name": "Ping An Bank",
                    "l1_code": "801780.SI",
                    "l1_name": "Bank",
                    "in_date": "20200101",
                    "out_date": "",
                    "is_new": "Y",
                }
            ]
        ),
    )

    rows = build_daily_panel(settings)
    assert rows == 1

    report_path = run_quality_checks(settings, expected_trade_dates=["20260525"])
    report = report_path.read_text(encoding="utf-8")
    assert "PASS 主键重复检查" in report
    assert "申万历史行业归属匹配率: 100.00%" in report
