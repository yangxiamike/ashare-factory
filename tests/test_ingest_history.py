from pathlib import Path

import duckdb
import pandas as pd

from ashare_data.config import Settings
from ashare_data.ingest import ingest_history, ingest_index_weight, ingest_recent


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

    def index_weight(self, index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        self._count(f"index_weight:{index_code}")
        rows = {
            "000300.SH": [
                {
                    "index_code": "000300.SH",
                    "con_code": "000001.SZ",
                    "trade_date": "20260525",
                    "weight": 3.1,
                },
                {
                    "index_code": "000300.SH",
                    "con_code": "000001.SZ",
                    "trade_date": "20260526",
                    "weight": 3.2,
                },
            ],
            "000905.SH": [
                {
                    "index_code": "000905.SH",
                    "con_code": "000002.SZ",
                    "trade_date": "20260525",
                    "weight": 1.5,
                },
                {
                    "index_code": "000905.SH",
                    "con_code": "000002.SZ",
                    "trade_date": "20260526",
                    "weight": 1.6,
                },
            ],
        }
        return pd.DataFrame(rows[index_code])


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
    assert first.failed == {endpoint: 0 for endpoint in ingest_module.DAILY_ENDPOINTS}
    assert first.skipped == {endpoint: 0 for endpoint in ingest_module.DAILY_ENDPOINTS}
    assert FakeTushareClient.calls["daily"] == 2

    second = ingest_history(
        settings,
        start_date="20260525",
        end_date="20260526",
        rate_limit_per_minute=0,
    )
    assert second.row_counts["daily"] == 0
    assert second.skipped["daily"] == 2
    assert second.skipped["adj_factor"] == 2
    assert FakeTushareClient.calls["daily"] == 2

    forced = ingest_history(
        settings,
        start_date="20260525",
        end_date="20260526",
        rate_limit_per_minute=0,
        force=True,
    )
    assert forced.failed == {endpoint: 0 for endpoint in ingest_module.DAILY_ENDPOINTS}
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
    assert first.failed == {endpoint: 0 for endpoint in ingest_module.DAILY_ENDPOINTS}

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


def test_ingest_index_weight_is_idempotent_and_keeps_multiple_indexes(tmp_path: Path, monkeypatch) -> None:
    import ashare_data.ingest as ingest_module

    FakeTushareClient.reset()
    monkeypatch.setattr(ingest_module, "TushareClient", FakeTushareClient)
    settings = _settings(tmp_path)

    first = ingest_index_weight(
        settings,
        start_date="20260525",
        end_date="20260526",
        index_codes=["000300.SH", "000905.SH"],
    )
    assert first.row_count == 4
    assert first.skipped == 0
    assert first.failed == 0

    second = ingest_index_weight(
        settings,
        start_date="20260525",
        end_date="20260526",
        index_codes=["000300.SH", "000905.SH"],
    )
    assert second.row_count == 0
    assert second.skipped == 4
    assert second.failed == 0
    assert FakeTushareClient.calls["index_weight:000300.SH"] == 2
    assert FakeTushareClient.calls["index_weight:000905.SH"] == 2

    forced = ingest_index_weight(
        settings,
        start_date="20260525",
        end_date="20260526",
        index_codes=["000300.SH", "000905.SH"],
        force=True,
    )
    assert forced.row_count == 4

    with duckdb.connect(str(settings.duckdb_path)) as con:
        rows = con.execute(
            """
            SELECT index_code, con_code, trade_date, weight
            FROM index_weight
            ORDER BY index_code, trade_date
            """
        ).fetchall()
        statuses = con.execute(
            """
            SELECT endpoint, trade_date, status
            FROM ingest_status
            WHERE endpoint LIKE 'index_weight:%'
            ORDER BY endpoint, trade_date
            """
        ).fetchall()

    assert rows == [
        ("000300.SH", "000001.SZ", "20260525", 3.1),
        ("000300.SH", "000001.SZ", "20260526", 3.2),
        ("000905.SH", "000002.SZ", "20260525", 1.5),
        ("000905.SH", "000002.SZ", "20260526", 1.6),
    ]
    assert statuses == [
        ("index_weight:000300.SH", "20260525", "success"),
        ("index_weight:000300.SH", "20260526", "success"),
        ("index_weight:000905.SH", "20260525", "success"),
        ("index_weight:000905.SH", "20260526", "success"),
    ]

    assert (
        tmp_path
        / "data"
        / "raw"
        / "index_weight"
        / "index_code=000300.SH"
        / "trade_date=20260525"
        / "index_weight.parquet"
    ).exists()
