from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from factor_utils import (
    build_factor,
    compute_ic_decay,
    compute_momentum,
    load_daily_panel,
    neutralize_by_industry_and_size,
)


def test_load_daily_panel_uses_parameterized_start_date(tmp_path: Path) -> None:
    db_path = tmp_path / "panel.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE daily_panel (
                trade_date VARCHAR,
                ts_code VARCHAR,
                close DOUBLE,
                adj_factor DOUBLE,
                total_mv DOUBLE,
                is_suspended BOOLEAN,
                sw_l1_name VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_panel VALUES
            ('20220103', '000001.SZ', 10.0, 1.1, 1000.0, FALSE, 'Bank'),
            ('20220104', '000002.SZ', 11.0, 0.9, 2000.0, FALSE, 'Broker')
            """
        )

    df = load_daily_panel(db_path, "99999999' OR 1=1 --")

    assert df.empty
    with duckdb.connect(str(db_path), read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM daily_panel").fetchone()[0] == 2


def test_load_daily_panel_adds_adj_close(tmp_path: Path) -> None:
    db_path = tmp_path / "panel.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE daily_panel (
                trade_date VARCHAR,
                ts_code VARCHAR,
                close DOUBLE,
                adj_factor DOUBLE,
                total_mv DOUBLE,
                is_suspended BOOLEAN,
                sw_l1_name VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_panel VALUES
            ('20220103', '000001.SZ', 10.0, 1.2, 1000.0, FALSE, 'Bank')
            """
        )

    df = load_daily_panel(db_path, "20220101")

    assert list(df.columns) == [
        "trade_date",
        "ts_code",
        "close",
        "adj_factor",
        "total_mv",
        "is_suspended",
        "sw_l1_name",
        "adj_close",
    ]
    assert df.loc[0, "adj_close"] == 12.0


def test_load_daily_panel_keeps_industry_and_optional_limit_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "panel.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE daily_panel (
                trade_date VARCHAR,
                ts_code VARCHAR,
                close DOUBLE,
                adj_factor DOUBLE,
                total_mv DOUBLE,
                is_suspended BOOLEAN,
                sw_l1_name VARCHAR,
                open DOUBLE,
                up_limit DOUBLE,
                down_limit DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_panel VALUES
            ('20220103', '000001.SZ', 10.0, 1.0, 1000.0, FALSE, 'Bank', 10.0, 11.0, 9.0),
            ('20220104', '000001.SZ', 11.0, 1.0, 1000.0, FALSE, 'Bank', 12.1, 12.1, 9.9)
            """
        )

    df = load_daily_panel(db_path, "20220101")

    assert "sw_l1_name" in df.columns
    assert {"open", "up_limit", "down_limit"}.issubset(df.columns)
    assert df.loc[0, "next_open_is_limit_up"]


def test_compute_momentum_supports_custom_column_name() -> None:
    df = pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=4),
            "ts_code": ["000001.SZ"] * 4,
            "adj_close": [10.0, 11.0, 12.0, 15.0],
        }
    )

    result = compute_momentum(df, window=2, col_name="mom_20d", dropna=False)

    assert "mom_20d" in result.columns
    assert np.isnan(result.loc[0, "mom_20d"])
    assert result.loc[3, "mom_20d"] == 15.0 / 11.0 - 1


def test_neutralize_by_industry_and_size_removes_linear_exposures() -> None:
    total_mv = np.linspace(100.0, 1200.0, 12)
    industry = np.array(["Bank"] * 6 + ["Tech"] * 6)
    residual_seed = np.array([-0.3, 0.2, -0.1, 0.4, -0.2, 0.0, 0.1, -0.4, 0.3, -0.2, 0.2, 0.0])
    df = pd.DataFrame(
        {
            "trade_date": pd.Timestamp("2024-01-02"),
            "ts_code": [f"{i:06d}.SZ" for i in range(12)],
            "total_mv": total_mv,
            "sw_l1_name": industry,
            "factor_zscore": 2.0 * np.log(total_mv) + (industry == "Tech") * 3.0 + residual_seed,
        }
    )

    result = neutralize_by_industry_and_size(df, "factor_zscore")
    neutral = result["factor_industry_size_neutral"]

    assert neutral.notna().sum() == 12
    assert abs(neutral.mean()) < 1e-12
    assert abs(neutral.std(ddof=0) - 1.0) < 1e-12
    assert abs(neutral.corr(pd.Series(np.log(total_mv)))) < 1e-12
    assert abs(neutral.corr(pd.Series((industry == "Tech").astype(float)))) < 1e-12


def test_build_factor_selects_industry_size_neutralization() -> None:
    df = pd.DataFrame(
        {
            "trade_date": pd.Timestamp("2024-01-02"),
            "ts_code": [f"{i:06d}.SZ" for i in range(12)],
            "total_mv": np.linspace(100.0, 1200.0, 12),
            "sw_l1_name": ["Bank"] * 6 + ["Tech"] * 6,
            "mom": np.linspace(-0.1, 0.1, 12),
        }
    )

    result = build_factor(
        df,
        factor_col="mom",
        neutralization="industry_size",
        output_col="factor_industry_size_neutral",
    )

    assert "factor_raw" in result.columns
    assert "factor_zscore" in result.columns
    assert result["factor_industry_size_neutral"].notna().sum() == 12


def test_compute_ic_decay_summarizes_available_horizons() -> None:
    rows = []
    for dt in pd.date_range("2024-01-01", periods=2):
        for i in range(12):
            rows.append(
                {
                    "trade_date": dt,
                    "ts_code": f"{i:06d}.SZ",
                    "factor": i,
                    "fwd_1d": i,
                    "fwd_2d": 11 - i,
                }
            )
    df = pd.DataFrame(rows)

    decay = compute_ic_decay(df, "factor", max_lag=3)

    assert decay["horizon"].tolist() == [1, 2]
    assert decay.loc[decay["horizon"].eq(1), "mean_ic"].iloc[0] == 1.0
    assert decay.loc[decay["horizon"].eq(2), "mean_ic"].iloc[0] == -1.0
