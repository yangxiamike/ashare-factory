from __future__ import annotations

from datetime import datetime

from ashare_data.config import Settings
from ashare_data.storage import connect


def build_daily_panel(
    settings: Settings, start_date: str | None = None, end_date: str | None = None
) -> int:
    """Build daily_panel and return the row count for the affected range."""
    settings = settings.resolve_paths()
    _validate_range(start_date, end_date)
    select_sql, select_params = _panel_select_sql(settings, start_date, end_date)
    with connect(settings) as con:
        if start_date or end_date:
            con.execute("DROP TABLE IF EXISTS _daily_panel_range")
            con.execute(f"CREATE TEMP TABLE _daily_panel_range AS {select_sql}", select_params)
            if _daily_panel_schema_changed(con):
                full_sql, full_params = _panel_select_sql(settings, None, None)
                con.execute(f"CREATE OR REPLACE TABLE daily_panel AS {full_sql}", full_params)
                return con.execute(
                    """
                    SELECT COUNT(*)
                    FROM daily_panel
                    WHERE (? IS NULL OR trade_date >= ?)
                      AND (? IS NULL OR trade_date <= ?)
                    """,
                    [start_date, start_date, end_date, end_date],
                ).fetchone()[0]
            con.execute("CREATE TABLE IF NOT EXISTS daily_panel AS SELECT * FROM _daily_panel_range WHERE 1 = 0")
            con.execute(
                """
                DELETE FROM daily_panel
                WHERE (? IS NULL OR trade_date >= ?)
                  AND (? IS NULL OR trade_date <= ?)
                """,
                [start_date, start_date, end_date, end_date],
            )
            con.execute("INSERT INTO daily_panel SELECT * FROM _daily_panel_range")
            return con.execute(
                """
                SELECT COUNT(*)
                FROM daily_panel
                WHERE (? IS NULL OR trade_date >= ?)
                  AND (? IS NULL OR trade_date <= ?)
                """,
                [start_date, start_date, end_date, end_date],
            ).fetchone()[0]

        con.execute(f"CREATE OR REPLACE TABLE daily_panel AS {select_sql}", select_params)
        return con.execute("SELECT COUNT(*) FROM daily_panel").fetchone()[0]


def _panel_select_sql(
    settings: Settings, start_date: str | None, end_date: str | None
) -> tuple[str, list[str | None]]:
    sql = (settings.sql_dir / "build_daily_panel.sql").read_text(encoding="utf-8")
    return sql, [start_date, start_date, end_date, end_date]


def _daily_panel_schema_changed(con) -> bool:
    existing_columns = {
        row[0]
        for row in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = 'daily_panel'
            """
        ).fetchall()
    }
    range_columns = {
        row[0]
        for row in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = '_daily_panel_range'
            """
        ).fetchall()
    }
    return bool(existing_columns) and existing_columns != range_columns


def _validate_range(start_date: str | None, end_date: str | None) -> None:
    if (start_date is None) != (end_date is None):
        raise ValueError("start_date and end_date must be provided together")
    if start_date is None and end_date is None:
        return
    assert start_date is not None and end_date is not None
    for label, value in (("start_date", start_date), ("end_date", end_date)):
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise ValueError(f"{label} must be in YYYYMMDD format, got: {value}") from exc
    if start_date > end_date:
        raise ValueError(f"start_date must be <= end_date, got {start_date} > {end_date}")
