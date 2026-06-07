from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


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
