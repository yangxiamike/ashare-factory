from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import duckdb

from ashare_data.config import Settings


PRIMARY_KEY_TABLES = ("daily", "daily_basic", "daily_panel")
DAILY_ENDPOINTS = ("daily", "adj_factor", "daily_basic", "suspend_d", "stk_limit")
KEY_MISSING_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "amount",
    "adj_factor",
    "turnover_rate",
    "total_mv",
)


@dataclass(frozen=True)
class CheckResult:
    title: str
    status: str
    summary: str
    details: list[str]


def run_quality_checks(
    settings: Settings,
    expected_trade_dates: Iterable[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Path:
    settings = settings.resolve_paths()
    duckdb_path = settings.duckdb_path
    report_dir = _resolve_report_dir(settings)
    report_dir.mkdir(parents=True, exist_ok=True)

    expected_dates = sorted({str(item) for item in (expected_trade_dates or [])})
    with duckdb.connect(str(duckdb_path)) as con:
        tables = _list_tables(con)
        if not expected_dates and start_date and end_date and "trade_cal" in tables:
            expected_dates = _expected_dates_from_trade_cal(con, start_date, end_date)
        results = [
            _check_ingest_status(con, tables, expected_dates),
            _check_primary_key_duplicates(con, tables, start_date, end_date),
            _check_date_coverage(con, tables, expected_dates, start_date, end_date),
            _check_missing_rates(con, tables, start_date, end_date),
            _check_ohlc_sanity(con, tables, start_date, end_date),
            _check_daily_basic_coverage(con, tables, start_date, end_date),
            _check_industry_match(con, tables, start_date, end_date),
        ]

    report = _render_report(duckdb_path, tables, results, expected_dates, start_date, end_date)
    if start_date or end_date:
        report_name = (
            f"history_dq_{start_date or 'BEGIN'}_{end_date or 'END'}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )
    else:
        report_name = f"dq_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = report_dir / report_name
    report_path.write_text(report, encoding="utf-8")
    return report_path


def _resolve_report_dir(settings: Settings) -> Path:
    return settings.report_dir


def _list_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [
        row[0]
        for row in con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
            """
        ).fetchall()
    ]


def _columns(con: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [table_name],
        ).fetchall()
    }


def _date_filter_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"(? IS NULL OR {prefix}trade_date >= ?) AND (? IS NULL OR {prefix}trade_date <= ?)"


def _date_params(start_date: str | None, end_date: str | None) -> list[str | None]:
    return [start_date, start_date, end_date, end_date]


def _expected_dates_from_trade_cal(
    con: duckdb.DuckDBPyConnection, start_date: str, end_date: str
) -> list[str]:
    return [
        str(row[0])
        for row in con.execute(
            """
            SELECT cal_date
            FROM trade_cal
            WHERE CAST(is_open AS VARCHAR) = '1'
              AND cal_date >= ?
              AND cal_date <= ?
            ORDER BY cal_date
            """,
            [start_date, end_date],
        ).fetchall()
    ]


def _check_ingest_status(
    con: duckdb.DuckDBPyConnection, tables: list[str], expected_dates: list[str]
) -> CheckResult:
    if "ingest_status" not in tables:
        return CheckResult("历史采集状态", "WARN", "未找到 ingest_status 表。", [])
    if not expected_dates:
        return CheckResult("历史采集状态", "PASS", "未指定预期交易日，跳过缺口判断。", [])

    details: list[str] = []
    failures: list[str] = []
    for endpoint in DAILY_ENDPOINTS:
        success_dates = {
            str(row[0])
            for row in con.execute(
                """
                SELECT DISTINCT trade_date
                FROM ingest_status
                WHERE endpoint = ? AND status = 'success'
                """,
                [endpoint],
            ).fetchall()
        }
        failed_count = con.execute(
            "SELECT COUNT(*) FROM ingest_status WHERE endpoint = ? AND status = 'failed'",
            [endpoint],
        ).fetchone()[0]
        missing = [item for item in expected_dates if item not in success_dates]
        details.append(
            f"- `{endpoint}`: success `{len(success_dates)}`, failed `{failed_count}`, "
            f"missing expected `{len(missing)}`"
        )
        if failed_count or missing:
            failures.append(endpoint)
    if failures:
        return CheckResult("历史采集状态", "WARN", f"存在失败或缺口接口: {', '.join(failures)}", details)
    return CheckResult("历史采集状态", "PASS", "历史采集状态完整。", details)


def _check_primary_key_duplicates(
    con: duckdb.DuckDBPyConnection,
    tables: list[str],
    start_date: str | None,
    end_date: str | None,
) -> CheckResult:
    details: list[str] = []
    failures: list[str] = []
    for table in PRIMARY_KEY_TABLES:
        if table not in tables or not {"trade_date", "ts_code"}.issubset(_columns(con, table)):
            continue
        duplicates = con.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT trade_date, ts_code
                FROM {table}
                WHERE {_date_filter_sql()}
                GROUP BY trade_date, ts_code
                HAVING COUNT(*) > 1
            )
            """,
            _date_params(start_date, end_date),
        ).fetchone()[0]
        details.append(f"- `{table}`: duplicate key groups `{duplicates}`")
        if duplicates:
            failures.append(f"`{table}`={duplicates}")
    if failures:
        return CheckResult("主键重复检查", "FAIL", f"发现重复主键: {', '.join(failures)}", details)
    if details:
        return CheckResult("主键重复检查", "PASS", "未发现 `trade_date + ts_code` 重复。", details)
    return CheckResult("主键重复检查", "WARN", "未找到可检查主键的目标表。", details)


def _check_date_coverage(
    con: duckdb.DuckDBPyConnection,
    tables: list[str],
    expected_dates: list[str],
    start_date: str | None,
    end_date: str | None,
) -> CheckResult:
    details: list[str] = []
    missing_by_table: list[str] = []
    for table in ("daily", "daily_basic", "daily_panel"):
        if table not in tables or "trade_date" not in _columns(con, table):
            continue
        min_date, max_date, date_count = con.execute(
            f"""
            SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date)
            FROM {table}
            WHERE {_date_filter_sql()}
            """,
            _date_params(start_date, end_date),
        ).fetchone()
        details.append(f"- `{table}`: covers `{date_count}` trade dates, `{min_date}` to `{max_date}`")
        if expected_dates:
            existing = {
                str(row[0])
                for row in con.execute(
                    f"SELECT DISTINCT trade_date FROM {table} WHERE {_date_filter_sql()}",
                    _date_params(start_date, end_date),
                ).fetchall()
            }
            missing = [item for item in expected_dates if item not in existing]
            if missing:
                missing_by_table.append(f"`{table}` missing {', '.join(missing[:20])}")
    if missing_by_table:
        return CheckResult("日期覆盖检查", "FAIL", "; ".join(missing_by_table), details)
    if details:
        return CheckResult("日期覆盖检查", "PASS", "交易日覆盖已检查。", details)
    return CheckResult("日期覆盖检查", "WARN", "未找到带 `trade_date` 的目标表。", details)


def _check_missing_rates(
    con: duckdb.DuckDBPyConnection, tables: list[str], start_date: str | None, end_date: str | None
) -> CheckResult:
    details: list[str] = []
    alerts: list[str] = []
    checked_any = False
    for table in ("daily_panel", "daily", "daily_basic"):
        if table not in tables:
            continue
        fields = [field for field in KEY_MISSING_FIELDS if field in _columns(con, table)]
        if not fields:
            continue
        total = con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {_date_filter_sql()}",
            _date_params(start_date, end_date),
        ).fetchone()[0]
        if total == 0:
            details.append(f"- `{table}`: empty table in range, skipped")
            continue
        checked_any = True
        for field in fields:
            missing = con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {_date_filter_sql()} AND {field} IS NULL",
                _date_params(start_date, end_date),
            ).fetchone()[0]
            rate = missing / total
            details.append(f"- `{table}.{field}`: missing `{missing}/{total}`, rate `{rate:.2%}`")
            if rate > 0.05:
                alerts.append(f"`{table}.{field}`={rate:.2%}")
    if not checked_any:
        return CheckResult("关键字段缺失率", "WARN", "目标表缺少可检查字段或范围内为空。", details)
    if alerts:
        return CheckResult("关键字段缺失率", "WARN", f"超过 5% 的字段: {', '.join(alerts)}", details)
    return CheckResult("关键字段缺失率", "PASS", "关键字段缺失率在阈值内。", details)


def _check_ohlc_sanity(
    con: duckdb.DuckDBPyConnection, tables: list[str], start_date: str | None, end_date: str | None
) -> CheckResult:
    table = "daily_panel" if "daily_panel" in tables else "daily" if "daily" in tables else None
    if table is None or not {"open", "high", "low", "close"}.issubset(_columns(con, table)):
        return CheckResult("OHLC 合理性检查", "WARN", "未找到可检查 OHLC 的表。", [])
    invalid = con.execute(
        f"""
        SELECT COUNT(*)
        FROM {table}
        WHERE {_date_filter_sql()}
          AND (
              open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
              OR high < low
              OR open < low OR open > high
              OR close < low OR close > high
          )
        """,
        _date_params(start_date, end_date),
    ).fetchone()[0]
    status = "FAIL" if invalid else "PASS"
    summary = "发现 OHLC 价格逻辑异常。" if invalid else "OHLC 价格逻辑正常。"
    return CheckResult("OHLC 合理性检查", status, summary, [f"- `{table}`: invalid OHLC rows `{invalid}`"])


def _check_daily_basic_coverage(
    con: duckdb.DuckDBPyConnection, tables: list[str], start_date: str | None, end_date: str | None
) -> CheckResult:
    if "daily" not in tables or "daily_basic" not in tables:
        return CheckResult("daily 与 daily_basic 覆盖差异", "WARN", "缺少 daily 或 daily_basic。", [])
    params = _date_params(start_date, end_date)
    daily_missing = con.execute(
        f"""
        SELECT COUNT(*)
        FROM daily d
        LEFT JOIN daily_basic b ON d.trade_date = b.trade_date AND d.ts_code = b.ts_code
        WHERE {_date_filter_sql('d')} AND b.ts_code IS NULL
        """,
        params,
    ).fetchone()[0]
    basic_extra = con.execute(
        f"""
        SELECT COUNT(*)
        FROM daily_basic b
        LEFT JOIN daily d ON d.trade_date = b.trade_date AND d.ts_code = b.ts_code
        WHERE {_date_filter_sql('b')} AND d.ts_code IS NULL
        """,
        params,
    ).fetchone()[0]
    details = [
        f"- `daily` has rows missing in `daily_basic`: `{daily_missing}`",
        f"- `daily_basic` has rows missing in `daily`: `{basic_extra}`",
    ]
    if daily_missing or basic_extra:
        return CheckResult("daily 与 daily_basic 覆盖差异", "WARN", "两张表覆盖不完全一致。", details)
    return CheckResult("daily 与 daily_basic 覆盖差异", "PASS", "两张表主键覆盖一致。", details)


def _check_industry_match(
    con: duckdb.DuckDBPyConnection, tables: list[str], start_date: str | None, end_date: str | None
) -> CheckResult:
    if "daily_panel" not in tables or "sw_l1_code" not in _columns(con, "daily_panel"):
        return CheckResult("申万历史行业归属匹配率", "WARN", "缺少 daily_panel 行业字段。", [])
    total, matched = con.execute(
        f"""
        SELECT COUNT(*), SUM(CASE WHEN sw_l1_code IS NOT NULL THEN 1 ELSE 0 END)
        FROM daily_panel
        WHERE {_date_filter_sql()}
        """,
        _date_params(start_date, end_date),
    ).fetchone()
    rate = (matched or 0) / total if total else 0
    status = "PASS" if rate >= 0.95 else "WARN"
    return CheckResult(
        "申万历史行业归属匹配率",
        status,
        f"申万历史行业归属匹配率 {rate:.2%}",
        [f"- `daily_panel.sw_l1_code`: matched `{matched or 0}/{total}`, rate `{rate:.2%}`"],
    )


def _render_report(
    duckdb_path: Path,
    tables: list[str],
    results: list[CheckResult],
    expected_dates: list[str],
    start_date: str | None,
    end_date: str | None,
) -> str:
    counts = {status: sum(item.status == status for item in results) for status in ("PASS", "WARN", "FAIL")}
    title = "A股日频历史补数质检报告" if start_date or end_date else "A股日频数据底座一期质检报告"
    lines = [
        f"# {title}",
        "",
        f"- 生成时间: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"- DuckDB: `{duckdb_path}`",
        f"- 日期范围: `{start_date or 'BEGIN'}` ~ `{end_date or 'END'}`",
        f"- 预期交易日数量: `{len(expected_dates)}`",
        f"- 已发现表: {', '.join(f'`{table}`' for table in tables) if tables else '无'}",
        "",
        "## 总览",
        "",
        f"- PASS: `{counts['PASS']}`",
        f"- WARN: `{counts['WARN']}`",
        f"- FAIL: `{counts['FAIL']}`",
    ]
    for result in results:
        lines.extend(["", f"## {result.status} {result.title}", "", result.summary])
        if result.details:
            lines.extend(["", *result.details])
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 主键默认按 `trade_date + ts_code` 检查。",
            "- `daily_panel` 的行业归属来自 `index_member_all` 的历史区间匹配结果。",
            "- 历史补数报告用于暴露接口失败、日期缺口、字段缺失和行业匹配问题。",
        ]
    )
    return "\n".join(lines) + "\n"
