from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from ashare_radar.data_input import daily_panel_coverage, load_daily_panel, load_daily_panel_window
from ashare_radar.industry_strength_ranking import rank_industry_strength
from ashare_radar.market_temperature import evaluate_market_temperature
from ashare_radar.news_intake import build_news_digest
from ashare_radar.report_generator import render_daily_report, write_daily_report
from ashare_radar.style_factor_ranking import DEFAULT_STYLE_CONFIG_PATH, load_style_bucket_configs, rank_style_factors


DEFAULT_NEWS_CONFIG_PATH = Path("configs") / "ashare_radar" / "news.yaml"
app = typer.Typer(help="A-share radar minimal CLI.")


def _compact_trade_date(value: str) -> str:
    return date.fromisoformat(value).strftime("%Y%m%d")


def _fail(exc: Exception) -> None:
    typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1) from exc


@app.command()
def news(
    date: str = typer.Option(..., "--date", help="Trade date in YYYY-MM-DD format."),
    config_path: Path = typer.Option(DEFAULT_NEWS_CONFIG_PATH, "--config-path", help="Path to radar news config."),
) -> None:
    """Run the minimal radar news pipeline."""
    try:
        digest = build_news_digest(date, config_path=config_path)
        typer.echo(f"trade_date: {digest['trade_date']}")
        typer.echo(
            "pipeline_counts: "
            f"raw={digest['total_raw']} clean={digest['total_clean']} "
            f"deduped={digest['total_deduped']} relevant={digest['total_relevant']}"
        )
        for index, item in enumerate(digest["items"], start=1):
            typer.echo(f"{index}. [{item['category']}] score={item['score']} {item['title']} ({item['source']})")
    except Exception as exc:
        _fail(exc)


@app.command()
def daily(
    date: str = typer.Option(..., "--date", help="Trade date in YYYY-MM-DD format."),
    lookback_days: int = typer.Option(5, "--lookback-days", help="Lookback window for market/industry stats."),
    news_config_path: Path = typer.Option(
        DEFAULT_NEWS_CONFIG_PATH,
        "--news-config-path",
        help="Path to radar news config.",
    ),
    style_config_path: Path = typer.Option(
        DEFAULT_STYLE_CONFIG_PATH,
        "--style-config-path",
        help="Path to radar style config.",
    ),
    report_path: Path | None = typer.Option(
        None,
        "--report-path",
        help="Optional explicit output path for the Markdown report.",
    ),
) -> None:
    """Run the daily radar pipeline and write a Markdown report."""
    try:
        trade_date = _compact_trade_date(date)
        history_panel = load_daily_panel_window(trade_date=trade_date, lookback_days=lookback_days)
        daily_panel = load_daily_panel(trade_date=trade_date)
        coverage = daily_panel_coverage()
        style_configs = load_style_bucket_configs(style_config_path)
        market_temperature = evaluate_market_temperature(history_panel=history_panel, trade_date=trade_date)
        style_ranking = rank_style_factors(daily_panel=daily_panel, trade_date=trade_date, style_configs=style_configs)
        industry_ranking = rank_industry_strength(history_panel=history_panel, trade_date=trade_date)
        news_digest = build_news_digest(date, config_path=news_config_path)
        report_text = render_daily_report(
            trade_date=date,
            market_temperature=market_temperature,
            style_ranking=style_ranking,
            industry_ranking=industry_ranking,
            news_digest=news_digest,
        )
        output_path = write_daily_report(trade_date=date, report_text=report_text, report_path=report_path)

        typer.echo(f"trade_date: {date}")
        typer.echo(
            "market_temperature: "
            f"state={market_temperature.state} "
            f"score={market_temperature.score}"
        )
        typer.echo(
            "coverage: "
            f"{coverage['min_trade_date']} -> {coverage['max_trade_date']} "
            f"rows={coverage['row_count']}"
        )
        typer.echo(f"news_items: {news_digest['total_relevant']}")
        typer.echo(f"report: {output_path}")
    except Exception as exc:
        _fail(exc)


if __name__ == "__main__":
    app()
