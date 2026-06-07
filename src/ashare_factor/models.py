from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


DAILY_PANEL_FIELDS = frozenset(
    {
        "trade_date",
        "ts_code",
        "name",
        "market",
        "area",
        "stock_basic_industry",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
        "adj_factor",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
        "up_limit",
        "down_limit",
        "is_suspended",
        "suspend_type",
        "suspend_timing",
        "sw_member_name",
        "sw_l1_code",
        "sw_l1_name",
        "sw_l2_code",
        "sw_l2_name",
        "sw_l3_code",
        "sw_l3_name",
        "sw_in_date",
        "sw_out_date",
        "sw_is_new",
    }
)


@dataclass(frozen=True)
class FactorSpec:
    factor_id: str
    factor_name: str
    category: str
    formula_text: str
    implementation: str
    params: dict[str, Any]
    direction: str
    lookback_days: int
    data_fields: list[str]
    status: str
    description: str
    hypothesis: str

    def __post_init__(self) -> None:
        if self.direction not in {"positive", "negative"}:
            raise ValueError(f"direction must be positive or negative: {self.factor_id}")
        if self.status != "candidate":
            raise ValueError(f"registry status must stay candidate: {self.factor_id}")


@dataclass(frozen=True)
class SampleConfig:
    universe_name: str
    start_date: str | None = None
    end_date: str | None = None
    require_main_board: bool = True
    exclude_st: bool = True
    min_listing_days: int = 60
    min_amount: float = 1_000_000.0
    new_stock_window_days: int = 20
    forward_horizons: tuple[int, ...] = (1, 3, 5, 10, 20)
    min_cross_section_count: int = 30


@dataclass(frozen=True)
class PreprocessConfig:
    winsorize_method: str = "mad"
    winsorize_n_mad: float = 3.0
    neutralize: str = "industry_size"
    re_standardize_after_neutralize: bool = True


@dataclass(frozen=True)
class EvaluationConfig:
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    evaluation: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)
    output_root: Path = Path("outputs")
    report_root: Path = Path("reports/factor_evaluation")

    @property
    def primary_horizon(self) -> int:
        return int(self.evaluation.get("primary_horizon", 5))

    @property
    def n_quantiles(self) -> int:
        return int(self.evaluation.get("n_quantiles", 5))

    @property
    def rebalance_days(self) -> int:
        return int(self.evaluation.get("rebalance_days", 5))

    @property
    def one_way_cost(self) -> float:
        return float(self.evaluation.get("one_way_cost", 0.001))

    @property
    def neutralize(self) -> str:
        return self.preprocess.neutralize

    @property
    def winsorize_n_mad(self) -> float:
        return self.preprocess.winsorize_n_mad

    @property
    def min_cross_section_count(self) -> int:
        return int(self.evaluation.get("min_cross_section_count", 30))

    @property
    def rolling_ic_window(self) -> int:
        return int(self.evaluation.get("rolling_ic_window", 252))


@dataclass(frozen=True)
class DataSnapshot:
    duckdb_path: str
    min_trade_date: str | None
    max_trade_date: str | None
    row_count: int


@dataclass
class SampleResult:
    sample: pd.DataFrame
    config: SampleConfig
    data_snapshot: DataSnapshot
    skipped_dates: list[str]


@dataclass(frozen=True)
class GateDecision:
    status: str
    reasons: list[str]
    validity: dict[str, Any] = field(default_factory=dict)
    research_evidence: dict[str, Any] = field(default_factory=dict)
    library_decision: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationResult:
    factor_id: str
    metrics: dict[str, Any]
    data_snapshot: DataSnapshot
    status: str = "candidate"
    run_id: str = ""
    code_version: dict[str, Any] = field(default_factory=dict)
    gate_decision: GateDecision | None = None
    baseline_comparison: dict[str, Any] = field(default_factory=dict)
    oos: dict[str, Any] = field(default_factory=dict)
    output_paths: dict[str, str] = field(default_factory=dict)


def parse_yaml_like(text: str) -> Any:
    lines = [_strip_comment(line.rstrip("\n")) for line in text.splitlines()]
    tokens = [(len(line) - len(line.lstrip(" ")), line.lstrip(" ")) for line in lines if line.strip()]
    if not tokens:
        return {}
    value, index = _parse_block(tokens, 0, tokens[0][0])
    if index != len(tokens):
        raise ValueError("Unexpected trailing YAML content")
    return value


def load_yaml_like(path: str | Path) -> Any:
    return parse_yaml_like(Path(path).read_text(encoding="utf-8"))


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    result: list[str] = []
    for char in line:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            break
        result.append(char)
    return "".join(result).rstrip()


def _parse_block(tokens: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(tokens):
        return {}, index
    if tokens[index][0] < indent:
        return {}, index
    if tokens[index][1] == "-" or tokens[index][1].startswith("- "):
        return _parse_list(tokens, index, indent)
    return _parse_mapping(tokens, index, indent)


def _parse_mapping(tokens: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(tokens):
        current_indent, content = tokens[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"Unexpected indentation near: {content}")
        if content == "-" or content.startswith("- "):
            break
        key, sep, raw_value = content.partition(":")
        if not sep:
            raise ValueError(f"Invalid YAML line: {content}")
        key = key.strip()
        value_text = raw_value.strip()
        index += 1
        if value_text:
            mapping[key] = _parse_scalar(value_text)
            continue
        if index >= len(tokens) or tokens[index][0] <= current_indent:
            mapping[key] = {}
            continue
        nested, index = _parse_block(tokens, index, tokens[index][0])
        mapping[key] = nested
    return mapping, index


def _parse_list(tokens: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(tokens):
        current_indent, content = tokens[index]
        if current_indent < indent:
            break
        if current_indent != indent or (content != "-" and not content.startswith("- ")):
            raise ValueError(f"Invalid YAML list item: {content}")
        value_text = "" if content == "-" else content[2:].strip()
        index += 1
        if value_text:
            items.append(_parse_scalar(value_text))
            continue
        if index >= len(tokens) or tokens[index][0] <= current_indent:
            items.append({})
            continue
        nested, index = _parse_block(tokens, index, tokens[index][0])
        items.append(nested)
    return items, index


def _parse_scalar(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none", "~"}:
        return None
    try:
        if any(char in value for char in [".", "e", "E"]):
            return float(value)
        return int(value)
    except ValueError:
        return value
