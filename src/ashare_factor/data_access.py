from __future__ import annotations

from pathlib import Path

import duckdb


def get_daily_panel_columns(duckdb_path: str | Path) -> set[str]:
    with duckdb.connect(str(duckdb_path), read_only=True) as con:
        rows = con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = 'daily_panel'
            """
        ).fetchall()
    return {str(row[0]) for row in rows}
