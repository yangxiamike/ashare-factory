from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ashare_radar.cli import app
from ashare_radar.models import (
    IndustryPerformance,
    IndustryStrengthRankingResult,
    MarketTemperatureResult,
    StyleBucketConfig,
    StyleBucketPerformance,
    StyleFactorRankingResult,
)


runner = CliRunner()


def test_news_command_outputs_ranked_digest() -> None:
    result = runner.invoke(app, ["news", "--date", "2026-06-08"])

    assert result.exit_code == 0
    assert "trade_date: 2026-06-08" in result.stdout
    assert "pipeline_counts:" in result.stdout
    assert "[macro]" in result.stdout


def test_daily_command_writes_report(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ashare_radar.cli.load_daily_panel_window",
        lambda trade_date, lookback_days: [{"trade_date": trade_date, "window": lookback_days}],
    )
    monkeypatch.setattr(
        "ashare_radar.cli.load_daily_panel",
        lambda trade_date: [{"trade_date": trade_date}],
    )
    monkeypatch.setattr(
        "ashare_radar.cli.daily_panel_coverage",
        lambda: {"min_trade_date": "20110104", "max_trade_date": "20260529", "row_count": 123},
    )
    monkeypatch.setattr(
        "ashare_radar.cli.load_style_bucket_configs",
        lambda path: {
            "size": StyleBucketConfig(
                factor_name="size",
                field="total_mv",
                side="high",
                top_label="large_cap",
                bottom_label="small_cap",
            )
        },
    )
    monkeypatch.setattr(
        "ashare_radar.cli.evaluate_market_temperature",
        lambda history_panel, trade_date: MarketTemperatureResult(
            trade_date=trade_date,
            score=72,
            state="risk_on",
            metrics={
                "average_return": 1.2,
                "median_return": 0.8,
                "amount_ratio_5d": 1.1,
                "up_count": 3000,
                "down_count": 1200,
                "up_limit_count": 88,
                "down_limit_count": 3,
            },
        ),
    )
    monkeypatch.setattr(
        "ashare_radar.cli.rank_style_factors",
        lambda daily_panel, trade_date, style_configs: StyleFactorRankingResult(
            trade_date=trade_date,
            rankings=[
                StyleBucketPerformance(
                    factor_name="size",
                    bucket_name="large_cap",
                    mean_return=1.0,
                    median_return=0.9,
                    stock_count=100,
                    field="total_mv",
                    side="high",
                )
            ],
            config=style_configs,
        ),
    )
    monkeypatch.setattr(
        "ashare_radar.cli.rank_industry_strength",
        lambda history_panel, trade_date: IndustryStrengthRankingResult(
            trade_date=trade_date,
            return_method="stock_aggregate",
            top=[
                IndustryPerformance(
                    industry_name="半导体",
                    mean_return=2.0,
                    median_return=1.8,
                    total_amount=1000.0,
                    stock_count=20,
                    advancer_ratio=0.8,
                    amount_ratio_5d=1.2,
                )
            ],
            bottom=[],
            volume_leaders=[],
            breadth={
                "industry_count": 1,
                "positive_industry_ratio": 1.0,
                "negative_industry_ratio": 0.0,
                "median_industry_return": 2.0,
            },
        ),
    )

    report_output = tmp_path / "reports" / "ashare_radar" / "2026-06-08.md"
    result = runner.invoke(
        app,
        [
            "daily",
            "--date",
            "2026-06-08",
            "--report-path",
            str(report_output),
        ],
    )

    assert result.exit_code == 0
    assert "market_temperature: state=risk_on score=72" in result.stdout
    assert "coverage: 20110104 -> 20260529 rows=123" in result.stdout
    assert report_output.exists()
    report_text = report_output.read_text(encoding="utf-8")
    assert "# A股 Market Radar - 2026-06-08" in report_text
    assert "## 新闻脉络" in report_text


def test_daily_command_reports_core_errors() -> None:
    result = runner.invoke(app, ["daily", "--date", "bad-date"])

    assert result.exit_code == 1
    assert "ERROR:" in result.stderr
