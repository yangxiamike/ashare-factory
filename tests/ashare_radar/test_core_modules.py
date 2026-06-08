from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ashare_data.config import Settings
from ashare_radar.data_input import daily_panel_coverage, load_daily_panel, load_daily_panel_window
from ashare_radar.industry_strength_ranking import rank_industry_strength
from ashare_radar.market_temperature import evaluate_market_temperature
from ashare_radar.report_generator import render_daily_report
from ashare_radar.style_factor_ranking import load_style_bucket_configs, rank_style_factors


def _write_daily_panel(path: Path) -> Settings:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as con:
        con.execute(
            """
            CREATE TABLE daily_panel (
                trade_date VARCHAR,
                ts_code VARCHAR,
                close DOUBLE,
                pre_close DOUBLE,
                pct_chg DOUBLE,
                amount DOUBLE,
                total_mv DOUBLE,
                pe_ttm DOUBLE,
                pb DOUBLE,
                turnover_rate DOUBLE,
                dv_ratio DOUBLE,
                is_suspended BOOLEAN,
                up_limit DOUBLE,
                down_limit DOUBLE,
                sw_l1_name VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_panel VALUES
            ('20260604', '000001.SZ', 10.0, 9.8, 2.0, 1000.0, 10000.0, 12.0, 1.2, 3.0, 1.0, FALSE, 10.8, 8.8, '银行'),
            ('20260604', '000002.SZ', 20.0, 20.5, -2.4, 800.0, 8000.0, 20.0, 2.0, 4.0, 0.5, FALSE, 22.6, 18.4, '地产'),
            ('20260605', '000001.SZ', 10.6, 10.0, 6.0, 1200.0, 10200.0, 12.5, 1.1, 3.2, 1.1, FALSE, 11.0, 9.0, '银行'),
            ('20260605', '000002.SZ', 19.4, 20.0, -3.0, 700.0, 7900.0, 19.5, 1.9, 4.5, 0.4, FALSE, 22.0, 18.0, '地产'),
            ('20260605', '000003.SZ', 15.5, 15.0, 3.3, 1500.0, 5000.0, 30.0, 4.0, 6.5, 0.2, FALSE, 16.5, 13.5, '半导体')
            """
        )
    return Settings(duckdb_path=path)


def test_data_input_reads_daily_panel(tmp_path: Path) -> None:
    settings = _write_daily_panel(tmp_path / "warehouse" / "ashare.duckdb")

    coverage = daily_panel_coverage(settings=settings)
    current = load_daily_panel("20260605", settings=settings)
    history = load_daily_panel_window("20260605", lookback_days=2, settings=settings)

    assert coverage["min_trade_date"] == "20260604"
    assert coverage["max_trade_date"] == "20260605"
    assert len(current) == 3
    assert set(history["trade_date"]) == {"20260604", "20260605"}


def test_market_temperature_outputs_state() -> None:
    frame = pd.DataFrame(
        [
            {"trade_date": "20260604", "pct_chg": 1.0, "amount": 900.0, "is_suspended": False, "close": 10.5, "up_limit": 11.0, "down_limit": 9.0},
            {"trade_date": "20260604", "pct_chg": -0.5, "amount": 800.0, "is_suspended": False, "close": 19.8, "up_limit": 22.0, "down_limit": 18.0},
            {"trade_date": "20260605", "pct_chg": 6.0, "amount": 1200.0, "is_suspended": False, "close": 10.9, "up_limit": 10.9, "down_limit": 9.0},
            {"trade_date": "20260605", "pct_chg": -3.0, "amount": 700.0, "is_suspended": False, "close": 19.0, "up_limit": 22.0, "down_limit": 18.0},
            {"trade_date": "20260605", "pct_chg": 3.3, "amount": 1500.0, "is_suspended": False, "close": 15.5, "up_limit": 16.5, "down_limit": 13.5},
        ]
    )

    result = evaluate_market_temperature(frame, "20260605")

    assert result.trade_date == "20260605"
    assert result.state in {"risk_on", "neutral", "risk_off"}
    assert "amount_ratio_5d" in result.metrics


def test_style_industry_and_report_pipeline(tmp_path: Path) -> None:
    settings = _write_daily_panel(tmp_path / "warehouse" / "ashare.duckdb")
    daily_panel = load_daily_panel("20260605", settings=settings)
    history_panel = load_daily_panel_window("20260605", lookback_days=2, settings=settings)
    style_config_path = tmp_path / "style_buckets.yaml"
    style_config_path.write_text(
        """
styles:
  size:
    factor_name: size
    field: total_mv
    side: high
    quantile: 0.34
    top_label: large_cap
    bottom_label: small_cap
""".strip(),
        encoding="utf-8",
    )

    style_result = rank_style_factors(
        daily_panel=daily_panel,
        trade_date="20260605",
        style_configs=load_style_bucket_configs(style_config_path),
    )
    industry_result = rank_industry_strength(history_panel=history_panel, trade_date="20260605")
    report_text = render_daily_report(
        trade_date="2026-06-05",
        market_temperature=evaluate_market_temperature(history_panel, "20260605"),
        style_ranking=style_result,
        industry_ranking=industry_result,
        news_digest={
            "total_raw": 2,
            "total_clean": 2,
            "total_deduped": 2,
            "total_relevant": 1,
            "items": [{"category": "macro", "score": 2.0, "title": "降准预期升温", "source": "mock"}],
        },
    )

    assert style_result.rankings
    assert industry_result.top
    assert "## 风格收益排名" in report_text
    assert "## 新闻脉络" in report_text
