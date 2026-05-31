from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import tushare as ts

from ashare_data.config import Settings


@dataclass(frozen=True)
class TushareClient:
    """Thin wrapper around Tushare Pro with explicit endpoint methods."""

    settings: Settings

    def __post_init__(self) -> None:
        object.__setattr__(self, "_pro", ts.pro_api(self.settings.require_token()))

    def trade_cal(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date)

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
        return self._pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date,act_name,act_ent_type",
        )

    def daily(self, trade_date: str) -> pd.DataFrame:
        return self._pro.daily(trade_date=trade_date)

    def adj_factor(self, trade_date: str) -> pd.DataFrame:
        return self._pro.adj_factor(trade_date=trade_date)

    def daily_basic(self, trade_date: str) -> pd.DataFrame:
        return self._pro.daily_basic(trade_date=trade_date)

    def suspend_d(self, trade_date: str) -> pd.DataFrame:
        return self._pro.suspend_d(trade_date=trade_date)

    def stk_limit(self, trade_date: str) -> pd.DataFrame:
        return self._pro.stk_limit(trade_date=trade_date)

    def index_classify(self) -> pd.DataFrame:
        return self._pro.index_classify(src="SW2021")

    def index_member_all(self) -> pd.DataFrame:
        return self._pro.index_member_all()
