from __future__ import annotations

from pathlib import Path

import duckdb

from ashare_data.config import Settings


def _load_sql(sql_path: Path) -> str:
    return sql_path.read_text(encoding="utf-8")


def build_daily_panel(settings: Settings) -> int:
    """Build daily_panel with trade_date + ts_code grain."""
    sql_path = Path(__file__).parent / "sql" / "build_daily_panel.sql"
    sql = _load_sql(sql_path)

    with duckdb.connect(str(settings.duckdb_path)) as conn:
        conn.execute(sql)
        row = conn.execute("SELECT COUNT(*) FROM daily_panel").fetchone()

    if row is None:
        return 0
    return int(row[0])
