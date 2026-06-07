import pandas as pd

from ashare_data.config import Settings
from ashare_data.tushare_client import TushareClient


def test_stock_basic_fetches_all_statuses(monkeypatch) -> None:
    captured: list[dict[str, str]] = []
    sentinel = object()

    def fake_call_with_retry(self, fn, **kwargs) -> pd.DataFrame:
        captured.append(kwargs)
        return pd.DataFrame([{"ts_code": f"00000{len(captured)}.SZ"}])

    monkeypatch.setattr(TushareClient, "__post_init__", lambda self: None)
    monkeypatch.setattr(TushareClient, "_call_with_retry", fake_call_with_retry)

    client = TushareClient(Settings(TUSHARE_TOKEN="test-token"))
    object.__setattr__(client, "_pro", type("FakePro", (), {"stock_basic": sentinel})())
    frame = client.stock_basic()

    assert [item["list_status"] for item in captured] == ["L", "D", "P"]
    assert all(item["exchange"] == "" for item in captured)
    assert all("list_date" in item["fields"] for item in captured)
    assert len(frame) == 3


def test_index_member_all_fetches_current_and_historical_rows(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    def fake_query_all(self, api_name: str, page_size: int = 3000, **kwargs) -> pd.DataFrame:
        calls.append({"api_name": api_name, "page_size": str(page_size), **kwargs})
        return pd.DataFrame(
            [
                {
                    "ts_code": "600185.SH",
                    "l1_code": "801200.SI" if kwargs["is_new"] == "Y" else "801180.SI",
                    "in_date": "20260305" if kwargs["is_new"] == "Y" else "19990611",
                    "out_date": None if kwargs["is_new"] == "Y" else "20260304",
                    "is_new": kwargs["is_new"],
                }
            ]
        )

    monkeypatch.setattr(TushareClient, "__post_init__", lambda self: None)
    monkeypatch.setattr(TushareClient, "_query_all", fake_query_all)

    client = TushareClient(Settings(TUSHARE_TOKEN="test-token"))
    frame = client.index_member_all()

    assert [call["is_new"] for call in calls] == ["Y", "N"]
    assert len(frame) == 2
    assert set(frame["is_new"]) == {"Y", "N"}


def test_index_weight_passes_date_range_and_keeps_expected_columns(monkeypatch) -> None:
    captured: dict[str, str] = {}
    sentinel = object()

    def fake_call_with_retry(self, fn, **kwargs) -> pd.DataFrame:
        captured.update(kwargs)
        return pd.DataFrame(
            [
                {
                    "index_code": "000300.SH",
                    "con_code": "000001.SZ",
                    "trade_date": "20260530",
                    "weight": 3.2,
                    "extra": "ignored",
                }
            ]
        )

    monkeypatch.setattr(TushareClient, "__post_init__", lambda self: None)
    monkeypatch.setattr(TushareClient, "_call_with_retry", fake_call_with_retry)

    client = TushareClient(Settings(TUSHARE_TOKEN="test-token"))
    object.__setattr__(client, "_pro", type("FakePro", (), {"index_weight": sentinel})())
    frame = client.index_weight("000300.SH", "20260501", "20260531")

    assert captured == {
        "index_code": "000300.SH",
        "start_date": "20260501",
        "end_date": "20260531",
    }
    assert frame.to_dict(orient="records") == [
        {
            "index_code": "000300.SH",
            "con_code": "000001.SZ",
            "trade_date": "20260530",
            "weight": 3.2,
        }
    ]
