from pathlib import Path
import sys
import types

import duckdb

sys.modules.setdefault("yaml", types.SimpleNamespace(safe_load=lambda text: {}))

from ashare_data.config import Settings
from ashare_factor.models import SampleConfig
from ashare_factor.sample_builder.sample import build_sample


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


def test_build_sample_uses_calendar_days_since_listing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.warehouse_dir.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(settings.duckdb_path)) as con:
        con.execute(
            """
            CREATE TABLE daily_panel (
                trade_date VARCHAR,
                ts_code VARCHAR,
                name VARCHAR,
                market VARCHAR,
                list_date VARCHAR,
                open DOUBLE,
                close DOUBLE,
                amount DOUBLE,
                adj_factor DOUBLE,
                total_mv DOUBLE,
                up_limit DOUBLE,
                down_limit DOUBLE,
                is_suspended BOOLEAN,
                sw_l1_name VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_panel VALUES
            ('20150105', '000001.SZ', 'Ping An', '主板', '20100101', 10.0, 10.5, 2000.0, 1.0, 1000.0, 11.0, 9.0, FALSE, 'Bank')
            """
        )

    config = SampleConfig(
        universe_name="main_board",
        start_date="20150105",
        end_date="20150105",
        require_main_board=True,
        exclude_st=False,
        min_listing_days=84,
        min_amount=1000.0,
        new_stock_window_days=28,
        min_cross_section_count=1,
    )

    result = build_sample(config=config, settings=settings)

    assert len(result.sample) == 1
    assert result.sample.loc[0, "listed_trade_days"] > 1800
