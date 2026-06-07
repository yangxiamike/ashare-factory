from __future__ import annotations

from pathlib import Path
from typing import Any

from .metrics import to_plain_dict


def write_evaluation_report(
    eval_result: dict[str, Any] | Any,
    *,
    output_path: str | Path | None = None,
) -> Path:
    result = to_plain_dict(eval_result)
    requested_path = Path(output_path or result.get("output_paths", {}).get("report_markdown") or "reports/factor_evaluation/report.md")
    path = _write_with_fallback(requested_path, _render_markdown(result))
    if isinstance(eval_result, dict):
        eval_result.setdefault("output_paths", {})
        eval_result["output_paths"]["report_markdown"] = str(path)
    return path


def _write_with_fallback(path: Path, content: str) -> Path:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
    except PermissionError:
        fallback = Path("outputs") / "factor_evaluation" / path.name
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(content, encoding="utf-8")
        return fallback


def _render_markdown(result: dict[str, Any]) -> str:
    full_sample = result.get("metrics", {}).get("full_sample", {})
    in_sample = result.get("oos_evidence", {}).get("in_sample", {})
    oos = result.get("oos_evidence", {}).get("out_of_sample", {})
    gate = result.get("gate_decision", {})
    baseline = result.get("baseline_comparison", {})

    lines = [
        f"# Factor Evaluation Report: {result['factor_id']}",
        "",
        "## Summary",
        "",
        f"- Status: `{gate.get('status', 'unknown')}`",
        f"- Run ID: `{result.get('run_id', '')}`",
        f"- Evaluated At: `{result.get('evaluated_at', '')}`",
        f"- Direction: `{result.get('direction', '')}`",
        f"- Primary Horizon: `{result.get('primary_horizon', '')}`",
        "",
        "## Gate",
        "",
        f"- Final Status: `{gate.get('status', 'unknown')}`",
        f"- Reasons: {', '.join(gate.get('reasons', [])) or 'None'}",
        f"- Validity: `{gate.get('validity', {}).get('status', 'unknown')}`",
        f"- Research Evidence: `{gate.get('research_evidence', {}).get('status', 'unknown')}`",
        f"- Library Decision: `{gate.get('library_decision', {}).get('status', 'unknown')}`",
        "",
        "## Reproducibility",
        "",
        f"- Data Snapshot: `{result.get('data_snapshot', {})}`",
        f"- Code Version: `{result.get('code_version', {})}`",
        "",
        "## Full Sample Metrics",
        "",
        _metric_table(full_sample),
        "",
        "## IS / OOS",
        "",
        "### In Sample",
        "",
        _metric_table(in_sample),
        "",
        "### Out of Sample",
        "",
        _metric_table(oos),
        "",
        "## Baseline Comparison",
        "",
        _baseline_section(baseline),
        "",
        "## Output Paths",
        "",
        f"- Report: `{result.get('output_paths', {}).get('report_markdown', '')}`",
        f"- Library: `{result.get('output_paths', {}).get('factor_library_json', '')}`",
        "",
        "## Notes",
        "",
        "- Evaluation uses direction-adjusted metrics for gate decisions.",
        "- 预处理顺序为 winsorize(MAD, n=3) -> cross-sectional zscore -> industry+size regression residual -> re-standardize。",
        "- 中性化发生在 zscore 之后，回归 beta 反映的是标准化因子值与行业/市值暴露的关系。",
    ]
    return "\n".join(lines).strip() + "\n"


def _metric_table(metrics: dict[str, Any]) -> str:
    rank_ic = metrics.get("rank_ic", {})
    quantile = metrics.get("quantile", {})
    top = metrics.get("top_quantile", {})
    turnover = metrics.get("turnover", {})
    long_short = metrics.get("long_short", {})
    rows = [
        "| Metric | Value |",
        "| --- | --- |",
        f"| Coverage | {metrics.get('coverage_pct', 'n/a')} |",
        f"| Valid Dates | {metrics.get('n_valid_dates', 'n/a')} |",
        f"| RankIC Mean | {rank_ic.get('mean', 'n/a')} |",
        f"| RankIC IR | {rank_ic.get('ir', 'n/a')} |",
        f"| RankIC T-Stat | {rank_ic.get('t_stat', 'n/a')} |",
        f"| Q5-Q1 Spread Mean | {quantile.get('q5_q1_spread_mean', 'n/a')} |",
        f"| Top Quantile Return | {top.get('mean_return', 'n/a')} |",
        f"| Top Quantile Sharpe | {top.get('sharpe', 'n/a')} |",
        f"| Top Quantile Max Drawdown | {top.get('max_drawdown', 'n/a')} |",
        f"| Mean Turnover | {turnover.get('mean_turnover', 'n/a')} |",
        f"| Turnover Std | {turnover.get('turnover_std', 'n/a')} |",
        f"| Long-Short Sharpe | {long_short.get('sharpe', 'n/a')} |",
    ]
    return "\n".join(rows)


def _baseline_section(baseline: dict[str, Any]) -> str:
    if not baseline:
        return "- No baseline evidence."
    groups = baseline.get("groups", {})
    if not groups:
        return f"- Baseline status: `{baseline.get('status', 'unknown')}`"
    lines = []
    for group_name, payload in groups.items():
        lines.append(f"### {group_name}")
        lines.append("")
        lines.append(f"- Status: `{payload.get('status', 'unknown')}`")
        if payload.get("reason"):
            lines.append(f"- Reason: {payload['reason']}")
        metrics = payload.get("metrics", {})
        for metric_name, values in metrics.items():
            lines.append(
                f"- {metric_name}: candidate={values.get('candidate')}, "
                f"baseline_median={values.get('baseline_median')}, percentile={values.get('percentile')}"
            )
        lines.append("")
    return "\n".join(lines).rstrip()
