from ashare_data.ingest import _month_chunks, ingest_history_verbose
from tests.test_ingest_history import FakeTushareClient, _settings


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
