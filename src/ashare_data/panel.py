from __future__ import annotations

from ashare_data.config import Settings
from ashare_data.storage import connect


def build_daily_panel(settings: Settings) -> int:
    """Build daily_panel and return the row count."""
    settings = settings.resolve_paths()
    sql = (settings.sql_dir / "build_daily_panel.sql").read_text(encoding="utf-8")
    with connect(settings) as con:
        con.execute(sql)
        return con.execute("SELECT COUNT(*) FROM daily_panel").fetchone()[0]
