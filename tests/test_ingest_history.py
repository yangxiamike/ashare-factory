from pathlib import Path

import duckdb
import pandas as pd

from ashare_data.config import Settings
from ashare_data.ingest import ingest_history, ingest_recent


class FakeTushareClient:
    calls: dict[str, int] = {}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    def reset(cls) -> None:
        cls.calls = {}

    def _count(self, endpoint: str) -> None:
        self.calls[endpoint] = self.calls.get(endpoint, 0) + 1

    def trade_cal(self, start_date: str, end_date: str) -> pd.DataFrame:
        self._count("trade_cal")
        return pd.DataFrame(
            [
                {"exchange": "SSE", "cal_date": "20260525", "is_open": "1"},
                {"exchange": "SSE", "cal_date": "20260526", "is_open": "1"},
            ]
        )

    def recent_trade_calendar(self, days: int = 5, lookback_days: int = 45) -> tuple[pd.DataFrame, list[str]]:
        frame = self.trade_cal("20260525", "20260526")
        return frame, ["20260525", "20260526"][-days:]

    def stock_basic(self) -> pd.DataFrame:
        self._count("stock_basic")
        return pd.DataFrame([{"ts_code": "000001.SZ", "name": "Ping An Bank"}])

    def index_classify(self) -> pd.DataFrame:
        self._count("index_classify")
        return pd.DataFrame([{"index_code": "801780.SI", "industry_name": "Bank"}])

    def index_member_all(self) -> pd.DataFrame:
        self._count("index_member_all")
        return pd.DataFrame([{"ts_code": "000001.SZ", "l1_code": "801780.SI", "in_date": "20200101"}])

    def daily(self, trade_date: str) -> pd.DataFrame:
        self._count("daily")
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "open": 10.0}])

    def adj_factor(self, trade_date: str) -> pd.DataFrame:
        self._count("adj_factor")
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "adj_factor": 1.0}])

    def daily_basic(self, trade_date: str) -> pd.DataFrame:
        self._count("daily_basic")
        return pd.DataFrame(
            [{"ts_code": "000001.SZ", "trade_date": trade_date, "turnover_rate": 1.0}]
        )

    def suspend_d(self, trade_date: str) -> pd.DataFrame:
        self._count("suspend_d")
        return pd.DataFrame()

    def stk_limit(self, trade_date: str) -> pd.DataFrame:
        self._count("stk_limit")
        return pd.DataFrame([{"ts_code": "000001.SZ", "trade_date": trade_date, "up_limit": 11.0}])


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        TUSHARE_TOKEN="test-token",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        raw_dir=tmp_path / "data" / "raw",
        warehouse_dir=tmp_path / "data" / "warehouse",
        report_dir=tmp_path / "reports" / "dq",
        duckdb_path=tmp_path / "data" / "warehouse" / "ashare.duckdb",
    )


def test_ingest_history_skips_successful_partitions_and_force_refetches(
    tmp_path: Path, monkeypatch
) -> None:
    import ashare_data.ingest as ingest_module

    FakeTushareClient.reset()
    monkeypatch.setattr(ingest_module, "TushareClient", FakeTushareClient)
    settings = _settings(tmp_path)

    first = ingest_history(
        settings,
        start_date="20260525",
        end_date="20260526",
        rate_limit_per_minute=0,
    )
    assert first.failed == {}
    assert FakeTushareClient.calls["daily"] == 2

    second = ingest_history(
        settings,
        start_date="20260525",
        end_date="20260526",
        rate_limit_per_minute=0,
    )
    assert second.skipped["daily"] == 2
    assert FakeTushareClient.calls["daily"] == 2

    forced = ingest_history(
        settings,
        start_date="20260525",
        end_date="20260526",
        rate_limit_per_minute=0,
        force=True,
    )
    assert forced.failed == {}
    assert FakeTushareClient.calls["daily"] == 4

    partition = tmp_path / "data" / "raw" / "daily" / "trade_date=20260525" / "daily.parquet"
    assert partition.exists()
    with duckdb.connect(str(settings.duckdb_path)) as con:
        daily_rows = con.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
        success_rows = con.execute(
            "SELECT COUNT(*) FROM ingest_status WHERE endpoint='daily' AND status='success'"
        ).fetchone()[0]
    assert daily_rows == 2
    assert success_rows == 2


def test_ingest_recent_upserts_daily_tables_without_dropping_history(
    tmp_path: Path, monkeypatch
) -> None:
    import ashare_data.ingest as ingest_module

    FakeTushareClient.reset()
    monkeypatch.setattr(ingest_module, "TushareClient", FakeTushareClient)
    settings = _settings(tmp_path)

    first = ingest_history(
        settings,
        start_date="20260525",
        end_date="20260526",
        rate_limit_per_minute=0,
    )
    assert first.failed == {}

    recent = ingest_recent(settings, days=1)
    assert recent.trade_dates == ["20260526"]

    with duckdb.connect(str(settings.duckdb_path)) as con:
        daily_dates = con.execute("SELECT trade_date FROM daily ORDER BY trade_date").fetchall()
        adj_dates = con.execute("SELECT trade_date FROM adj_factor ORDER BY trade_date").fetchall()
        basic_dates = con.execute("SELECT trade_date FROM daily_basic ORDER BY trade_date").fetchall()
        limit_dates = con.execute("SELECT trade_date FROM stk_limit ORDER BY trade_date").fetchall()

    expected = [("20260525",), ("20260526",)]
    assert daily_dates == expected
    assert adj_dates == expected
    assert basic_dates == expected
    assert limit_dates == expected
