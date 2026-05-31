from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ashare_data.config import Settings
from ashare_data.storage import initialize_warehouse, replace_table, write_raw
from ashare_data.tushare_client import TushareClient


@dataclass(frozen=True)
class IngestResult:
    trade_dates: list[str]
    row_counts: dict[str, int]


def _concat_daily(client: TushareClient, method_name: str, trade_dates: list[str]) -> pd.DataFrame:
    frames = []
    method = getattr(client, method_name)
    for trade_date in trade_dates:
        frame = method(trade_date)
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates(ignore_index=True)


def _persist(settings: Settings, endpoint: str, frame: pd.DataFrame) -> int:
    write_raw(settings, endpoint, frame)
    return replace_table(settings, endpoint, frame)


def ingest_recent(settings: Settings, days: int = 5) -> IngestResult:
    settings = settings.resolve_paths()
    initialize_warehouse(settings)
    client = TushareClient(settings)

    trade_cal, trade_dates = client.recent_trade_calendar(days=days)
    row_counts: dict[str, int] = {}

    row_counts["trade_cal"] = _persist(settings, "trade_cal", trade_cal)
    row_counts["stock_basic"] = _persist(settings, "stock_basic", client.stock_basic())

    for endpoint in ["daily", "adj_factor", "daily_basic", "suspend_d", "stk_limit"]:
        row_counts[endpoint] = _persist(settings, endpoint, _concat_daily(client, endpoint, trade_dates))

    row_counts["index_classify"] = _persist(settings, "index_classify", client.index_classify())
    row_counts["index_member_all"] = _persist(settings, "index_member_all", client.index_member_all())

    return IngestResult(trade_dates=trade_dates, row_counts=row_counts)
