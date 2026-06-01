import pandas as pd

from factor_eval.runner import _filter_by_index


def test_filter_by_index_forward_fills_rebalance_members():
    df = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(
                ["2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03", "2024-01-04"]
            ),
            "ts_code": ["A", "B", "A", "C", "C"],
            "value": [1, 2, 3, 4, 5],
        }
    )
    members = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-04"]),
            "ts_code": ["A", "B", "C"],
        }
    )

    result = _filter_by_index(df, members)

    assert result[["trade_date", "ts_code"]].to_records(index=False).tolist() == [
        (pd.Timestamp("2024-01-02"), "A"),
        (pd.Timestamp("2024-01-02"), "B"),
        (pd.Timestamp("2024-01-03"), "A"),
        (pd.Timestamp("2024-01-04"), "C"),
    ]

