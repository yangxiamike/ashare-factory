from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd

from ashare_data.config import Settings
from ashare_factor.data_access import get_daily_panel_columns
from ashare_factor.models import DataSnapshot, SampleConfig, SampleResult
from ashare_factor.sample_builder.forward_returns import build_forward_return_sql
from ashare_factor.sample_builder.universe import (
    DEFAULT_UNIVERSE_PATH,
    build_base_eligibility_sql,
    load_universe_config,
)


REQUIRED_SAMPLE_COLUMNS = {
    "trade_date",
    "ts_code",
    "name",
    "market",
    "list_date",
    "open",
    "close",
    "amount",
    "adj_factor",
    "total_mv",
    "up_limit",
    "down_limit",
    "is_suspended",
    "sw_l1_name",
}


def build_sample(
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    config: SampleConfig | None = None,
    config_path: str | Path = DEFAULT_UNIVERSE_PATH,
    settings: Settings | None = None,
) -> SampleResult:
    settings = (settings or Settings()).resolve_paths()
    sample_config = config or load_universe_config(config_path)
    if start_date or end_date:
        sample_config = replace(
            sample_config,
            start_date=start_date or sample_config.start_date,
            end_date=end_date or sample_config.end_date,
        )

    with duckdb.connect(str(settings.duckdb_path), read_only=True) as con:
        _ensure_daily_panel_columns(con)
        sample = con.execute(_build_sample_sql(sample_config)).fetchdf()
        snapshot_row = con.execute(
            """
            SELECT
                MIN(trade_date) AS min_trade_date,
                MAX(trade_date) AS max_trade_date,
                COUNT(*) AS row_count
            FROM daily_panel
            """
        ).fetchone()

    sample["trade_date"] = pd.to_datetime(sample["trade_date"])
    skipped_dates = (
        sample.loc[sample["tradable_count"] < sample_config.min_cross_section_count, "trade_date"]
        .dt.strftime("%Y%m%d")
        .drop_duplicates()
        .tolist()
    )
    if skipped_dates:
        skipped_set = {pd.Timestamp(item) for item in skipped_dates}
        sample = sample.loc[~sample["trade_date"].isin(skipped_set)].copy()
    sample = sample.drop(columns=["tradable_count"]).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

    snapshot = DataSnapshot(
        duckdb_path=str(settings.duckdb_path),
        min_trade_date=snapshot_row[0],
        max_trade_date=snapshot_row[1],
        row_count=int(snapshot_row[2]),
    )
    return SampleResult(
        sample=sample,
        config=sample_config,
        data_snapshot=snapshot,
        skipped_dates=skipped_dates,
    )


def _build_sample_sql(config: SampleConfig) -> str:
    start_filter = f"AND trade_date >= '{config.start_date}'" if config.start_date else ""
    end_filter = f"AND trade_date <= '{config.end_date}'" if config.end_date else ""
    forward_sql = build_forward_return_sql(config.forward_horizons)
    base_eligibility = build_base_eligibility_sql(config)
    return f"""
        WITH base AS (
            SELECT
                trade_date,
                ts_code,
                name,
                market,
                list_date,
                open,
                close,
                amount,
                adj_factor,
                total_mv,
                up_limit,
                down_limit,
                is_suspended,
                sw_l1_name,
                close * adj_factor AS adj_close,
                DATEDIFF(
                    'day',
                    STRPTIME(list_date, '%Y%m%d'),
                    STRPTIME(trade_date, '%Y%m%d')
                ) AS listed_trade_days,
                CASE
                    WHEN market = '主板' THEN TRUE
                    WHEN ts_code LIKE '600%%' OR ts_code LIKE '601%%'
                      OR ts_code LIKE '603%%' OR ts_code LIKE '605%%'
                      OR ts_code LIKE '000%%' OR ts_code LIKE '001%%'
                    THEN TRUE
                    ELSE FALSE
                END AS is_main_board,
                CASE
                    WHEN name LIKE 'ST%%' OR name LIKE '*ST%%' OR name LIKE 'S*ST%%'
                    THEN TRUE
                    ELSE FALSE
                END AS is_st,
                CASE
                    WHEN open IS NOT NULL AND up_limit IS NOT NULL AND open >= up_limit
                    THEN TRUE
                    ELSE FALSE
                END AS is_limit_up_at_open,
                CASE
                    WHEN open IS NOT NULL AND down_limit IS NOT NULL AND open <= down_limit
                    THEN TRUE
                    ELSE FALSE
                END AS is_limit_down_at_open
            FROM daily_panel
        ),
        dated AS (
            SELECT *
            FROM base
            WHERE 1 = 1
              {start_filter}
              {end_filter}
        ),
        flagged AS (
            SELECT
                *,
                {base_eligibility} AS passes_base_filters,
                {base_eligibility} AND NOT is_limit_up_at_open AS can_buy,
                {base_eligibility} AND NOT is_limit_down_at_open AS can_sell,
                {base_eligibility}
                    AND NOT is_limit_up_at_open
                    AND NOT is_limit_down_at_open AS is_tradable
            FROM dated
        ),
        with_returns AS (
            SELECT
                *,
                {forward_sql}
            FROM flagged
            WINDOW w AS (
                PARTITION BY ts_code
                ORDER BY trade_date
            )
        )
        SELECT
            *,
            SUM(CASE WHEN is_tradable THEN 1 ELSE 0 END) OVER (
                PARTITION BY trade_date
            ) AS tradable_count
        FROM with_returns
        ORDER BY trade_date, ts_code
    """


def _ensure_daily_panel_columns(con: duckdb.DuckDBPyConnection) -> None:
    available = {
        row[0]
        for row in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = 'daily_panel'
            """
        ).fetchall()
    }
    missing = REQUIRED_SAMPLE_COLUMNS - available
    if missing:
        raise ValueError(f"daily_panel missing required columns: {sorted(missing)}")


def ensure_daily_panel_columns(duckdb_path: str | Path) -> set[str]:
    available = get_daily_panel_columns(duckdb_path)
    missing = REQUIRED_SAMPLE_COLUMNS - available
    if missing:
        raise ValueError(f"daily_panel missing required columns: {sorted(missing)}")
    return available
