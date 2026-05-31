from pathlib import Path

import duckdb

from factor_utils import load_daily_panel


def test_load_daily_panel_uses_parameterized_start_date(tmp_path: Path) -> None:
    db_path = tmp_path / "panel.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE daily_panel (
                trade_date VARCHAR,
                ts_code VARCHAR,
                close DOUBLE,
                total_mv DOUBLE,
                is_suspended BOOLEAN,
                sw_l1_name VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_panel VALUES
            ('20220103', '000001.SZ', 10.0, 1000.0, FALSE, 'Bank'),
            ('20220104', '000002.SZ', 11.0, 2000.0, FALSE, 'Broker')
            """
        )

    df = load_daily_panel(db_path, "99999999' OR 1=1 --")

    assert df.empty
    with duckdb.connect(str(db_path), read_only=True) as con:
        assert con.execute("SELECT COUNT(*) FROM daily_panel").fetchone()[0] == 2
