from ashare_data.ingest import _month_chunks, ingest_history_verbose
from test_ingest_history import FakeTushareClient, _settings


def test_month_chunks_split_range_by_calendar_month() -> None:
    assert _month_chunks("20260515", "20260702") == [
        ("20260515", "20260531"),
        ("20260601", "20260630"),
        ("20260701", "20260702"),
    ]


def test_ingest_history_verbose_reports_progress(tmp_path, monkeypatch) -> None:
    import ashare_data.ingest as ingest_module

    FakeTushareClient.reset()
    monkeypatch.setattr(ingest_module, "TushareClient", FakeTushareClient)
    messages: list[str] = []

    result = ingest_history_verbose(
        _settings(tmp_path),
        start_date="20260525",
        end_date="20260526",
        rate_limit_per_minute=0,
        progress=messages.append,
    )

    assert len(result.chunks) == 1
    assert result.failed_total == 0
    assert len(result.trade_dates) == 2
    assert any("ETA=" in message for message in messages)
    assert any("failed=0" in message for message in messages)


def test_ingest_history_verbose_refreshes_static_tables_once_for_all_chunks(tmp_path, monkeypatch) -> None:
    import ashare_data.ingest as ingest_module
    import pandas as pd

    class MultiChunkFakeTushareClient(FakeTushareClient):
        def trade_cal(self, start_date: str, end_date: str) -> pd.DataFrame:
            self._count("trade_cal")
            rows = {
                ("20260531", "20260531"): [{"exchange": "SSE", "cal_date": "20260531", "is_open": "1"}],
                ("20260601", "20260601"): [{"exchange": "SSE", "cal_date": "20260601", "is_open": "1"}],
            }
            return pd.DataFrame(rows[(start_date, end_date)])

    MultiChunkFakeTushareClient.reset()
    monkeypatch.setattr(ingest_module, "TushareClient", MultiChunkFakeTushareClient)

    result = ingest_history_verbose(
        _settings(tmp_path),
        start_date="20260531",
        end_date="20260601",
        rate_limit_per_minute=0,
    )

    assert len(result.chunks) == 2
    assert MultiChunkFakeTushareClient.calls["stock_basic"] == 1
    assert MultiChunkFakeTushareClient.calls["index_classify"] == 1
    assert MultiChunkFakeTushareClient.calls["index_member_all"] == 1
    assert MultiChunkFakeTushareClient.calls["daily"] == 2
