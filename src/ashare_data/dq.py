from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import duckdb


PRIMARY_KEY_TABLES = ("daily", "daily_basic", "daily_panel")
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


def build_settings_for_path(
    duckdb_path: str | Path, report_dir: str | Path | None = None
) -> SimpleNamespace:
    """Small helper for tests and ad-hoc DQ runs without the full Settings object."""
    payload = {"duckdb_path": Path(duckdb_path)}
    if report_dir is not None:
        payload["report_dir"] = Path(report_dir)
    return SimpleNamespace(**payload)


def run_quality_checks(
    settings: object, expected_trade_dates: Iterable[str] | None = None
) -> Path:
    """Run phase-1 data quality checks and write a readable Markdown report."""
    duckdb_path = Path(getattr(settings, "duckdb_path"))
    report_dir = _resolve_report_dir(settings, duckdb_path)
    report_dir.mkdir(parents=True, exist_ok=True)

    expected_dates = sorted({str(item) for item in (expected_trade_dates or [])})
    with duckdb.connect(str(duckdb_path)) as con:
        tables = _list_tables(con)
        results = [
            _check_primary_key_duplicates(con, tables),
            _check_date_coverage(con, tables, expected_dates),
            _check_missing_rates(con, tables),
            _check_ohlc_sanity(con, tables),
            _check_daily_basic_coverage(con, tables),
            _check_industry_match(con, tables),
        ]

    report = _render_report(duckdb_path, tables, results, expected_dates)
    report_path = report_dir / f"dq_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path


def _resolve_report_dir(settings: object, duckdb_path: Path) -> Path:
    report_dir = getattr(settings, "report_dir", None)
    if report_dir:
        path = Path(report_dir)
        return path if path.name == "dq" else path / "dq"

    project_root = getattr(settings, "project_root", None)
    if project_root:
        return Path(project_root) / "reports" / "dq"

    return duckdb_path.resolve().parent / "reports" / "dq"


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


def _first_existing(candidates: Iterable[str], tables: Iterable[str]) -> str | None:
    available = set(tables)
    for candidate in candidates:
        if candidate in available:
            return candidate
    return None


def _check_primary_key_duplicates(
    con: duckdb.DuckDBPyConnection, tables: list[str]
) -> CheckResult:
    details: list[str] = []
    failures: list[str] = []

    for table in PRIMARY_KEY_TABLES:
        if table not in tables:
            continue
        if not {"trade_date", "ts_code"}.issubset(_columns(con, table)):
            details.append(f"- `{table}`: missing `trade_date + ts_code`, skipped")
            continue
        duplicates = con.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT trade_date, ts_code
                FROM {table}
                GROUP BY trade_date, ts_code
                HAVING COUNT(*) > 1
            )
            """
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
    con: duckdb.DuckDBPyConnection, tables: list[str], expected_dates: list[str]
) -> CheckResult:
    details: list[str] = []
    missing_by_table: list[str] = []

    for table in ("daily", "daily_basic", "daily_panel"):
        if table not in tables or "trade_date" not in _columns(con, table):
            continue
        min_date, max_date, date_count = con.execute(
            f"SELECT MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) FROM {table}"
        ).fetchone()
        details.append(f"- `{table}`: covers `{date_count}` trade dates, `{min_date}` to `{max_date}`")
        if expected_dates:
            existing = {
                str(row[0])
                for row in con.execute(f"SELECT DISTINCT trade_date FROM {table}").fetchall()
            }
            missing = [item for item in expected_dates if item not in existing]
            if missing:
                missing_by_table.append(f"`{table}` missing {', '.join(missing)}")

    if missing_by_table:
        return CheckResult("日期覆盖检查", "FAIL", "; ".join(missing_by_table), details)
    if details:
        return CheckResult("日期覆盖检查", "PASS", "交易日覆盖已检查。", details)
    return CheckResult("日期覆盖检查", "WARN", "未找到带 `trade_date` 的目标表。", details)


def _check_missing_rates(con: duckdb.DuckDBPyConnection, tables: list[str]) -> CheckResult:
    target_tables = [
        table_name
        for table_name in ("daily_panel", "daily", "daily_basic")
        if table_name in tables
    ]
    if not target_tables:
        return CheckResult("关键字段缺失率", "WARN", "未找到可检查字段缺失率的表。", [])

    details: list[str] = []
    alerts: list[str] = []
    checked_any = False

    for table in target_tables:
        columns = _columns(con, table)
        fields = [field for field in KEY_MISSING_FIELDS if field in columns]
        if not fields:
            continue

        total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if total == 0:
            details.append(f"- `{table}`: empty table, skipped")
            continue

        checked_any = True
        for field in fields:
            missing = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {field} IS NULL").fetchone()[0]
            rate = missing / total
            details.append(f"- `{table}.{field}`: missing `{missing}/{total}`, rate `{rate:.2%}`")
            if rate > 0.05:
                alerts.append(f"`{table}.{field}`={rate:.2%}")

    if not checked_any:
        return CheckResult("关键字段缺失率", "WARN", "目标表存在，但缺少可检查的关键字段。", details)
    if alerts:
        return CheckResult("关键字段缺失率", "WARN", f"超过 5% 的字段: {', '.join(alerts)}", details)
    return CheckResult("关键字段缺失率", "PASS", "关键字段缺失率在阈值内。", details)


def _check_ohlc_sanity(con: duckdb.DuckDBPyConnection, tables: list[str]) -> CheckResult:
    table = _first_existing(("daily_panel", "daily"), tables)
    if table is None or not {"open", "high", "low", "close"}.issubset(_columns(con, table)):
        return CheckResult("OHLC 合理性检查", "WARN", "未找到可检查 OHLC 的表。", [])

    invalid = con.execute(
        f"""
        SELECT COUNT(*)
        FROM {table}
        WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
           OR high < low
           OR open < low OR open > high
           OR close < low OR close > high
        """
    ).fetchone()[0]
    details = [f"- `{table}`: invalid OHLC rows `{invalid}`"]
    status = "FAIL" if invalid else "PASS"
    summary = "发现 OHLC 价格逻辑异常。" if invalid else "OHLC 价格逻辑正常。"
    return CheckResult("OHLC 合理性检查", status, summary, details)


def _check_daily_basic_coverage(
    con: duckdb.DuckDBPyConnection, tables: list[str]
) -> CheckResult:
    if "daily" not in tables or "daily_basic" not in tables:
        return CheckResult(
            "daily 与 daily_basic 覆盖差异",
            "WARN",
            "缺少 `daily` 或 `daily_basic`，无法比较覆盖差异。",
            [],
        )

    daily_missing = con.execute(
        """
        SELECT COUNT(*)
        FROM daily d
        LEFT JOIN daily_basic b
          ON d.trade_date = b.trade_date AND d.ts_code = b.ts_code
        WHERE b.ts_code IS NULL
        """
    ).fetchone()[0]
    basic_extra = con.execute(
        """
        SELECT COUNT(*)
        FROM daily_basic b
        LEFT JOIN daily d
          ON d.trade_date = b.trade_date AND d.ts_code = b.ts_code
        WHERE d.ts_code IS NULL
        """
    ).fetchone()[0]
    details = [
        f"- `daily` has rows missing in `daily_basic`: `{daily_missing}`",
        f"- `daily_basic` has rows missing in `daily`: `{basic_extra}`",
    ]
    if daily_missing or basic_extra:
        return CheckResult("daily 与 daily_basic 覆盖差异", "WARN", "两张表覆盖不完全一致。", details)
    return CheckResult("daily 与 daily_basic 覆盖差异", "PASS", "两张表主键覆盖一致。", details)


def _check_industry_match(con: duckdb.DuckDBPyConnection, tables: list[str]) -> CheckResult:
    if "daily_panel" in tables and "sw_l1_code" in _columns(con, "daily_panel"):
        total, matched = con.execute(
            """
            SELECT COUNT(*), SUM(CASE WHEN sw_l1_code IS NOT NULL THEN 1 ELSE 0 END)
            FROM daily_panel
            """
        ).fetchone()
        rate = (matched or 0) / total if total else 0
        details = [f"- `daily_panel.sw_l1_code`: matched `{matched or 0}/{total}`, rate `{rate:.2%}`"]
    elif "stock_industry_history" in tables and "daily" in tables:
        total, matched = con.execute(
            """
            SELECT COUNT(*), COUNT(CASE WHEN h.ts_code IS NOT NULL THEN 1 END)
            FROM daily d
            LEFT JOIN stock_industry_history h
              ON d.ts_code = h.ts_code
             AND d.trade_date >= h.in_date
             AND (h.out_date IS NULL OR h.out_date = '' OR d.trade_date < h.out_date)
            """
        ).fetchone()
        rate = (matched or 0) / total if total else 0
        details = [f"- `stock_industry_history`: matched `{matched or 0}/{total}`, rate `{rate:.2%}`"]
    else:
        return CheckResult("申万历史行业归属匹配率", "WARN", "缺少可计算行业匹配率的表或字段。", [])

    status = "PASS" if rate >= 0.95 else "WARN"
    summary = f"申万历史行业归属匹配率 {rate:.2%}"
    return CheckResult("申万历史行业归属匹配率", status, summary, details)


def _render_report(
    duckdb_path: Path,
    tables: list[str],
    results: list[CheckResult],
    expected_dates: list[str],
) -> str:
    counts = {
        status: sum(item.status == status for item in results) for status in ("PASS", "WARN", "FAIL")
    }
    lines = [
        "# A股日频数据底座一期质检报告",
        "",
        f"- 生成时间: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"- DuckDB: `{duckdb_path}`",
        f"- 已发现表: {', '.join(f'`{table}`' for table in tables) if tables else '无'}",
        f"- 预期交易日: `{', '.join(expected_dates)}`" if expected_dates else "- 预期交易日: 未指定",
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
            "- `daily_panel` 的行业归属应来自 `index_member_all` 的历史区间匹配结果。",
            "- 第一期只验证最近 5 个交易日闭环，报告用于暴露接口权限、覆盖率和字段质量问题。",
        ]
    )
    return "\n".join(lines) + "\n"
