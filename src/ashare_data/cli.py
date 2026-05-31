from pathlib import Path

import typer

from ashare_data.config import Settings
from ashare_data.dq import run_quality_checks
from ashare_data.ingest import ingest_recent
from ashare_data.panel import build_daily_panel
from ashare_data.storage import initialize_warehouse

app = typer.Typer(help="A-share daily data foundation CLI.")


def _settings() -> Settings:
    return Settings()


def _fail(exc: Exception) -> None:
    typer.secho(f"ERROR: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1) from exc


@app.command()
def init() -> None:
    """Initialize the local DuckDB warehouse schema."""
    try:
        settings = _settings()
        initialize_warehouse(settings)
        typer.echo(f"Initialized warehouse: {settings.duckdb_path}")
    except Exception as exc:
        _fail(exc)


@app.command()
def ingest(days: int = typer.Option(5, help="Number of recent open trading days to ingest.")) -> None:
    """Fetch recent Tushare data, save raw Parquet, and load DuckDB tables."""
    try:
        settings = _settings()
        result = ingest_recent(settings, days=days)
        typer.echo(f"Ingested trade dates: {', '.join(result.trade_dates)}")
        typer.echo(f"Raw data root: {settings.raw_dir}")
        typer.echo(f"Warehouse: {settings.duckdb_path}")
    except Exception as exc:
        _fail(exc)


@app.command("build-panel")
def build_panel() -> None:
    """Build the daily_panel table from normalized raw tables."""
    try:
        settings = _settings()
        rows = build_daily_panel(settings)
        typer.echo(f"Built daily_panel rows: {rows}")
    except Exception as exc:
        _fail(exc)


@app.command()
def dq() -> None:
    """Run data quality checks and write a Markdown report."""
    try:
        settings = _settings()
        report_path = run_quality_checks(settings)
        typer.echo(f"Wrote DQ report: {report_path}")
    except Exception as exc:
        _fail(exc)


@app.command()
def validate(days: int = typer.Option(5, help="Number of recent open trading days to validate.")) -> None:
    """Run the full phase-1 validation flow: init, ingest, panel, DQ."""
    try:
        settings = _settings()
        initialize_warehouse(settings)
        result = ingest_recent(settings, days=days)
        rows = build_daily_panel(settings)
        report_path = run_quality_checks(settings, expected_trade_dates=result.trade_dates)
        typer.echo(f"Validated trade dates: {', '.join(result.trade_dates)}")
        typer.echo(f"daily_panel rows: {rows}")
        typer.echo(f"DQ report: {Path(report_path)}")
    except Exception as exc:
        _fail(exc)


if __name__ == "__main__":
    app()
