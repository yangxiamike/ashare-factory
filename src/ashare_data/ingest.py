from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import monotonic, sleep
from typing import Callable

import pandas as pd

from ashare_data.config import Settings
from ashare_data.storage import (
    has_raw_daily_partition,
    has_successful_ingest,
    initialize_warehouse,
    record_ingest_status,
    replace_table,
    upsert_trade_cal_table,
    upsert_trade_date_table,
    write_raw,
    write_raw_partition,
)
from ashare_data.tushare_client import TushareClient


DAILY_ENDPOINTS = ["daily", "adj_factor", "daily_basic", "suspend_d", "stk_limit"]
STATIC_ENDPOINTS = ["stock_basic", "index_classify", "index_member_all"]


@dataclass(frozen=True)
class IngestResult:
    trade_dates: list[str]
    row_counts: dict[str, int]


@dataclass(frozen=True)
class HistoryIngestResult:
    trade_dates: list[str]
    row_counts: dict[str, int]
    skipped: dict[str, int]
    failed: dict[str, int]


@dataclass(frozen=True)
class HistoryChunkResult:
    chunk_index: int
    total_chunks: int
    start_date: str
    end_date: str
    result: HistoryIngestResult
    elapsed_seconds: float


@dataclass(frozen=True)
class VerboseHistoryIngestResult:
    chunks: list[HistoryChunkResult]

    @property
    def trade_dates(self) -> list[str]:
        dates: list[str] = []
        for chunk in self.chunks:
            dates.extend(chunk.result.trade_dates)
        return dates

    @property
    def failed_total(self) -> int:
        return sum(sum(chunk.result.failed.values()) for chunk in self.chunks)


class RateLimiter:
    def __init__(self, calls_per_minute: int) -> None:
        self.interval = 60 / calls_per_minute if calls_per_minute > 0 else 0
        self.last_call: datetime | None = None

    def wait(self) -> None:
        if self.interval <= 0:
            return
        now = datetime.now()
        if self.last_call is not None:
            elapsed = (now - self.last_call).total_seconds()
            if elapsed < self.interval:
                sleep(self.interval - elapsed)
        self.last_call = datetime.now()


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

    upsert_trade_cal_table(settings, trade_cal)
    row_counts["trade_cal"] = len(trade_cal)
    row_counts["stock_basic"] = _persist(settings, "stock_basic", client.stock_basic())

    for endpoint in DAILY_ENDPOINTS:
        row_counts[endpoint] = _persist_recent_daily_endpoint(settings, client, endpoint, trade_dates)

    row_counts["index_classify"] = _persist(settings, "index_classify", client.index_classify())
    row_counts["index_member_all"] = _persist(settings, "index_member_all", client.index_member_all())

    return IngestResult(trade_dates=trade_dates, row_counts=row_counts)


def ingest_history(
    settings: Settings,
    start_date: str | None = None,
    end_date: str | None = None,
    years: int | None = None,
    rate_limit_per_minute: int = 0,
    force: bool = False,
    retries: int = 2,
) -> HistoryIngestResult:
    settings = settings.resolve_paths()
    initialize_warehouse(settings)
    client = TushareClient(settings)

    start_date, end_date = _resolve_date_range(start_date, end_date, years)
    limiter = RateLimiter(rate_limit_per_minute)

    limiter.wait()
    trade_cal = client.trade_cal(start_date=start_date, end_date=end_date)
    if trade_cal.empty:
        raise RuntimeError(f"Tushare trade_cal returned no rows for {start_date} to {end_date}.")
    trade_dates = (
        trade_cal.loc[trade_cal["is_open"].astype(str) == "1", "cal_date"]
        .astype(str)
        .sort_values()
        .tolist()
    )
    upsert_trade_cal_table(settings, trade_cal)

    row_counts: dict[str, int] = {"trade_cal": len(trade_cal), **{endpoint: 0 for endpoint in DAILY_ENDPOINTS}}
    skipped: dict[str, int] = {endpoint: 0 for endpoint in DAILY_ENDPOINTS}
    failed: dict[str, int] = {endpoint: 0 for endpoint in DAILY_ENDPOINTS}

    for endpoint in STATIC_ENDPOINTS:
        frame = _call_with_retry(client, endpoint, limiter, retries)
        write_raw(settings, endpoint, frame)
        row_counts[endpoint] = replace_table(settings, endpoint, frame)
        record_ingest_status(settings, endpoint, "ALL", "success", row_counts[endpoint])

    for trade_date in trade_dates:
        for endpoint in DAILY_ENDPOINTS:
            if not force and has_successful_ingest(settings, endpoint, trade_date):
                if has_raw_daily_partition(settings, endpoint, trade_date):
                    skipped[endpoint] += 1
                    continue

            started_at: str | None = None
            try:
                started_at = datetime.now().isoformat(sep=" ", timespec="seconds")
                record_ingest_status(
                    settings, endpoint, trade_date, "running", started_at=started_at, finished_at=None
                )
                frame = _call_with_retry(client, endpoint, limiter, retries, trade_date)
                raw_path = write_raw_partition(settings, endpoint, trade_date, frame)
                row_counts[endpoint] += upsert_trade_date_table(settings, endpoint, trade_date, frame)
                record_ingest_status(
                    settings,
                    endpoint,
                    trade_date,
                    "success",
                    len(frame),
                    raw_path,
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(sep=" ", timespec="seconds"),
                )
            except Exception as exc:
                failed[endpoint] += 1
                record_ingest_status(
                    settings,
                    endpoint,
                    trade_date,
                    "failed",
                    error_message=str(exc),
                    started_at=started_at,
                    finished_at=datetime.now().isoformat(sep=" ", timespec="seconds"),
                )

    return HistoryIngestResult(
        trade_dates=trade_dates, row_counts=row_counts, skipped=skipped, failed=failed
    )


def ingest_history_verbose(
    settings: Settings,
    start_date: str | None = None,
    end_date: str | None = None,
    years: int | None = None,
    rate_limit_per_minute: int = 0,
    force: bool = False,
    retries: int = 2,
    progress: Callable[[str], None] | None = None,
) -> VerboseHistoryIngestResult:
    start_date, end_date = _resolve_date_range(start_date, end_date, years)
    chunks = _month_chunks(start_date, end_date)
    chunk_results: list[HistoryChunkResult] = []
    started = monotonic()

    for index, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        chunk_started = monotonic()
        _emit(
            progress,
            f"[{index}/{len(chunks)}] ingest {chunk_start}-{chunk_end} "
            f"({(index - 1) / len(chunks):.1%} complete)",
        )
        result = ingest_history(
            settings,
            start_date=chunk_start,
            end_date=chunk_end,
            rate_limit_per_minute=rate_limit_per_minute,
            force=force,
            retries=retries,
        )
        elapsed = monotonic() - chunk_started
        chunk_results.append(
            HistoryChunkResult(
                chunk_index=index,
                total_chunks=len(chunks),
                start_date=chunk_start,
                end_date=chunk_end,
                result=result,
                elapsed_seconds=elapsed,
            )
        )
        avg = (monotonic() - started) / index
        remaining = avg * (len(chunks) - index)
        _emit(
            progress,
            f"[{index}/{len(chunks)}] done {chunk_start}-{chunk_end}: "
            f"trade_dates={len(result.trade_dates)}, "
            f"success_rows={sum(result.row_counts.values())}, "
            f"skipped={sum(result.skipped.values())}, "
            f"failed={sum(result.failed.values())}, "
            f"elapsed={_format_duration(elapsed)}, "
            f"ETA={_format_duration(remaining)}",
        )

    return VerboseHistoryIngestResult(chunks=chunk_results)


def _resolve_date_range(
    start_date: str | None, end_date: str | None, years: int | None
) -> tuple[str, str]:
    if end_date is None:
        end_date = date.today().strftime("%Y%m%d")
    if start_date is None:
        if years is None:
            raise ValueError("Either --start-date or --years must be provided for ingest-history.")
        end = datetime.strptime(end_date, "%Y%m%d").date()
        try:
            start = end.replace(year=end.year - years)
        except ValueError:
            start = end - timedelta(days=365 * years)
        start_date = start.strftime("%Y%m%d")
    if start_date > end_date:
        raise ValueError("start_date must be <= end_date.")
    return start_date, end_date


def _month_chunks(start_date: str, end_date: str) -> list[tuple[str, str]]:
    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    chunks: list[tuple[str, str]] = []
    current = start
    while current <= end:
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month + 1, day=1)
        chunk_end = min(end, next_month - timedelta(days=1))
        chunks.append((current.strftime("%Y%m%d"), chunk_end.strftime("%Y%m%d")))
        current = chunk_end + timedelta(days=1)
    return chunks


def _emit(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def _call_with_retry(
    client: TushareClient,
    endpoint: str,
    limiter: RateLimiter,
    retries: int,
    trade_date: str | None = None,
) -> pd.DataFrame:
    method = getattr(client, endpoint)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            limiter.wait()
            if trade_date is None:
                return method()
            return method(trade_date)
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                sleep(2**attempt)
    raise RuntimeError(f"{endpoint} failed for {trade_date or 'ALL'}: {last_error}")


def _persist_recent_daily_endpoint(
    settings: Settings, client: TushareClient, endpoint: str, trade_dates: list[str]
) -> int:
    rows = 0
    method = getattr(client, endpoint)
    for trade_date in trade_dates:
        frame = method(trade_date)
        write_raw_partition(settings, endpoint, trade_date, frame)
        rows += upsert_trade_date_table(settings, endpoint, trade_date, frame)
    return rows
