from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from time import monotonic, sleep

import pandas as pd
import tushare as ts

from ashare_data.config import Settings


@dataclass(frozen=True)
class TushareClient:
    """Thin wrapper around Tushare Pro with explicit endpoint methods."""

    settings: Settings

    def __post_init__(self) -> None:
        object.__setattr__(self, "_pro", ts.pro_api(self.settings.require_token()))
        object.__setattr__(self, "_rate_limit_per_minute", 180)
        object.__setattr__(self, "_max_retries", 2)
        object.__setattr__(self, "_min_interval", 60 / self._rate_limit_per_minute)
        object.__setattr__(self, "_last_call_at", 0.0)

    def _wait_for_slot(self) -> None:
        now = monotonic()
        elapsed = now - self._last_call_at
        if elapsed < self._min_interval:
            sleep(self._min_interval - elapsed)
        object.__setattr__(self, "_last_call_at", monotonic())

    def _call_with_retry(self, fn, **kwargs) -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                self._wait_for_slot()
                return fn(**kwargs)
            except Exception as exc:  # pragma: no cover - network/runtime branch
                last_error = exc
                if attempt < self._max_retries:
                    sleep(2**attempt)
        raise RuntimeError(f"Tushare request failed after retries: {last_error}")

    def trade_cal(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._call_with_retry(self._pro.trade_cal, exchange="SSE", start_date=start_date, end_date=end_date)

    @staticmethod
    def open_dates_from_calendar(frame: pd.DataFrame, days: int) -> list[str]:
        open_days = (
            frame.loc[frame["is_open"].astype(str) == "1", "cal_date"]
            .astype(str)
            .sort_values()
            .tail(days)
            .tolist()
        )
        if len(open_days) < days:
            raise RuntimeError(f"Only found {len(open_days)} open trade dates, expected {days}.")
        return open_days

    def recent_trade_calendar(self, days: int = 5, lookback_days: int = 45) -> tuple[pd.DataFrame, list[str]]:
        end = date.today()
        start = end - timedelta(days=lookback_days)
        frame = self.trade_cal(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        if frame.empty:
            raise RuntimeError("Tushare trade_cal returned no rows; cannot determine trade dates.")
        return frame, self.open_dates_from_calendar(frame, days)

    def recent_open_dates(self, days: int = 5, lookback_days: int = 45) -> list[str]:
        return self.recent_trade_calendar(days=days, lookback_days=lookback_days)[1]

    def stock_basic(self) -> pd.DataFrame:
        return self._call_with_retry(
            self._pro.stock_basic,
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date,act_name,act_ent_type",
        )

    def daily(self, trade_date: str) -> pd.DataFrame:
        return self._call_with_retry(self._pro.daily, trade_date=trade_date)

    def adj_factor(self, trade_date: str) -> pd.DataFrame:
        return self._call_with_retry(self._pro.adj_factor, trade_date=trade_date)

    def daily_basic(self, trade_date: str) -> pd.DataFrame:
        return self._call_with_retry(self._pro.daily_basic, trade_date=trade_date)

    def suspend_d(self, trade_date: str) -> pd.DataFrame:
        return self._call_with_retry(self._pro.suspend_d, trade_date=trade_date)

    def stk_limit(self, trade_date: str) -> pd.DataFrame:
        return self._call_with_retry(self._pro.stk_limit, trade_date=trade_date)

    def index_classify(self) -> pd.DataFrame:
        return self._call_with_retry(self._pro.index_classify, src="SW2021")

    def index_member_all(self) -> pd.DataFrame:
        return self._query_all("index_member_all", page_size=3000)

    def _query_all(self, api_name: str, page_size: int = 3000, **kwargs) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        offset = 0
        while True:
            frame = self._call_with_retry(self._pro.query, api_name=api_name, limit=page_size, offset=offset, **kwargs)
            if frame.empty:
                break
            frames.append(frame)
            if len(frame) < page_size:
                break
            offset += page_size
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).drop_duplicates(ignore_index=True)
