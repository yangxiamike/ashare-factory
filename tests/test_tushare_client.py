import pandas as pd

from ashare_data.config import Settings
from ashare_data.tushare_client import TushareClient


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
