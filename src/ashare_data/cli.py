from pathlib import Path

import typer

from ashare_data.config import Settings
from ashare_data.dq import run_quality_checks
from ashare_data.ingest import ingest_history, ingest_history_verbose, ingest_index_weight, ingest_recent
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


@app.command("ingest-history")
def ingest_history_cmd(
    start_date: str | None = typer.Option(None, "--start-date", help="Start date (YYYYMMDD)."),
    end_date: str | None = typer.Option(None, "--end-date", help="End date (YYYYMMDD)."),
    years: int | None = typer.Option(None, "--years", help="Rolling years when start-date is not provided."),
    force: bool = typer.Option(False, "--force", help="Re-fetch partitions even when already successful."),
    rate_limit_per_minute: int = typer.Option(
        0,
        "--rate-limit-per-minute",
        help="Extra caller-side API calls per minute. 0 means rely on TushareClient rate limit.",
    ),
    retries: int = typer.Option(2, "--retries", help="Retry attempts per request."),
) -> None:
    """Historical ingest with resume/skip and partitioned raw output."""
    try:
        settings = _settings()
        result = ingest_history(
            settings,
            start_date=start_date,
            end_date=end_date,
            years=years,
            force=force,
            rate_limit_per_minute=rate_limit_per_minute,
            retries=retries,
        )
        typer.echo(f"Ingested trade dates: {len(result.trade_dates)}")
        typer.echo(f"Raw data root: {settings.raw_dir}")
        typer.echo(f"Warehouse: {settings.duckdb_path}")
    except Exception as exc:
        _fail(exc)


@app.command("ingest-history-verbose")
def ingest_history_verbose_cmd(
    start_date: str | None = typer.Option(None, "--start-date", help="Start date (YYYYMMDD)."),
    end_date: str | None = typer.Option(None, "--end-date", help="End date (YYYYMMDD)."),
    years: int | None = typer.Option(None, "--years", help="Rolling years when start-date is not provided."),
    force: bool = typer.Option(False, "--force", help="Re-fetch partitions even when already successful."),
    rate_limit_per_minute: int = typer.Option(
        0,
        "--rate-limit-per-minute",
        help="Extra caller-side API calls per minute. 0 means rely on TushareClient rate limit.",
    ),
    retries: int = typer.Option(2, "--retries", help="Retry attempts per request."),
) -> None:
    """Historical ingest by month with progress, ETA, and resume/skip output."""
    try:
        settings = _settings()
        result = ingest_history_verbose(
            settings,
            start_date=start_date,
            end_date=end_date,
            years=years,
            force=force,
            rate_limit_per_minute=rate_limit_per_minute,
            retries=retries,
            progress=typer.echo,
        )
        typer.echo(
            "Completed chunks: "
            f"{len(result.chunks)}, trade_dates={len(result.trade_dates)}, failed={result.failed_total}"
        )
    except Exception as exc:
        _fail(exc)


@app.command("ingest-index-weight")
def ingest_index_weight_cmd(
    start_date: str = typer.Option(..., "--start-date", help="Start date (YYYYMMDD)."),
    end_date: str = typer.Option(..., "--end-date", help="End date (YYYYMMDD)."),
    index_code: list[str] | None = typer.Option(None, "--index-code", help="Index code to ingest. Repeatable."),
    force: bool = typer.Option(False, "--force", help="Re-fetch partitions even when already successful."),
) -> None:
    """Fetch broad index constituent weights into raw partitions and DuckDB."""
    try:
        settings = _settings()
        result = ingest_index_weight(
            settings,
            start_date=start_date,
            end_date=end_date,
            index_codes=index_code,
            force=force,
        )
        typer.echo(f"Ingested index codes: {', '.join(result.index_codes)}")
        typer.echo(f"Ingested trade dates: {len(result.trade_dates)}")
        typer.echo(f"Rows written: {result.row_count}, skipped={result.skipped}, failed={result.failed}")
        typer.echo(f"Raw data root: {settings.raw_dir}")
        typer.echo(f"Warehouse: {settings.duckdb_path}")
    except Exception as exc:
        _fail(exc)


@app.command("build-panel")
def build_panel(
    start_date: str | None = typer.Option(None, "--start-date", help="Start date (YYYYMMDD)."),
    end_date: str | None = typer.Option(None, "--end-date", help="End date (YYYYMMDD)."),
) -> None:
    """Build the daily_panel table from normalized raw tables."""
    try:
        settings = _settings()
        initialize_warehouse(settings)
        rows = build_daily_panel(settings, start_date=start_date, end_date=end_date)
        typer.echo(f"Built daily_panel rows: {rows}")
    except Exception as exc:
        _fail(exc)


@app.command()
def dq(
    start_date: str | None = typer.Option(None, "--start-date", help="Inclusive start trade date, format YYYYMMDD."),
    end_date: str | None = typer.Option(None, "--end-date", help="Inclusive end trade date, format YYYYMMDD."),
) -> None:
    """Run data quality checks and write a Markdown report."""
    try:
        settings = _settings()
        initialize_warehouse(settings)
        report_path = run_quality_checks(settings, start_date=start_date, end_date=end_date)
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
