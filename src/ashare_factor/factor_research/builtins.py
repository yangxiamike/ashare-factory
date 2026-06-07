from __future__ import annotations

from collections.abc import Callable

import duckdb
import pandas as pd

from ashare_factor.models import FactorSpec


BuiltinCalculator = Callable[[pd.DataFrame, FactorSpec], pd.DataFrame]


def builtin_factor_ids() -> set[str]:
    return set(_BUILTIN_CALCULATORS)


def calculate_builtin_factor(sample: pd.DataFrame, spec: FactorSpec) -> pd.DataFrame:
    calculator = _BUILTIN_CALCULATORS.get(spec.implementation)
    if calculator is None:
        raise ValueError(f"Unsupported builtin implementation: {spec.implementation}")
    return calculator(sample, spec)


def _momentum_return(sample: pd.DataFrame, spec: FactorSpec) -> pd.DataFrame:
    window = int(spec.params.get("window", spec.lookback_days))
    sql = f"""
        SELECT
            trade_date,
            ts_code,
            '{spec.factor_id}' AS factor_id,
            adj_close / LAG(adj_close, {window}) OVER w - 1 AS factor_value_raw
        FROM sample
        WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date)
        ORDER BY trade_date, ts_code
    """
    return _run_factor_sql(sample, sql)


def _rolling_volatility(sample: pd.DataFrame, spec: FactorSpec) -> pd.DataFrame:
    window = int(spec.params.get("window", spec.lookback_days))
    sql = f"""
        WITH returns AS (
            SELECT
                *,
                adj_close / LAG(adj_close) OVER w - 1 AS daily_return
            FROM sample
            WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date)
        )
        SELECT
            trade_date,
            ts_code,
            '{spec.factor_id}' AS factor_id,
            CASE
                WHEN COUNT(daily_return) OVER w = {window}
                THEN STDDEV_SAMP(daily_return) OVER w
                ELSE NULL
            END AS factor_value_raw
        FROM returns
        WINDOW w AS (
            PARTITION BY ts_code
            ORDER BY trade_date
            ROWS BETWEEN {window - 1} PRECEDING AND CURRENT ROW
        )
        ORDER BY trade_date, ts_code
    """
    return _run_factor_sql(sample, sql)


def _run_factor_sql(sample: pd.DataFrame, sql: str) -> pd.DataFrame:
    with duckdb.connect() as con:
        con.register("sample", sample)
        result = con.execute(sql).fetchdf()
        con.unregister("sample")
    result["trade_date"] = pd.to_datetime(result["trade_date"])
    return result


_BUILTIN_CALCULATORS: dict[str, BuiltinCalculator] = {
    "builtin:momentum_return": _momentum_return,
    "builtin:short_term_return": _momentum_return,
    "builtin:rolling_volatility": _rolling_volatility,
}
