from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RadarState = Literal["risk_on", "neutral", "risk_off"]
SortDirection = Literal["high", "low"]


@dataclass(frozen=True)
class MarketTemperatureResult:
    trade_date: str
    score: int
    state: RadarState
    metrics: dict[str, Any]


@dataclass(frozen=True)
class StyleBucketConfig:
    factor_name: str
    field: str
    side: SortDirection
    quantile: float = 0.2
    top_label: str = "top"
    bottom_label: str = "bottom"

    def __post_init__(self) -> None:
        if self.side not in {"high", "low"}:
            raise ValueError(f"unsupported style side: {self.side}")
        if not 0 < self.quantile < 0.5:
            raise ValueError(f"quantile must be between 0 and 0.5: {self.quantile}")


@dataclass(frozen=True)
class StyleBucketPerformance:
    factor_name: str
    bucket_name: str
    mean_return: float
    median_return: float
    stock_count: int
    field: str
    side: SortDirection


@dataclass(frozen=True)
class StyleFactorRankingResult:
    trade_date: str
    rankings: list[StyleBucketPerformance]
    config: dict[str, StyleBucketConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class IndustryPerformance:
    industry_name: str
    mean_return: float
    median_return: float
    total_amount: float
    stock_count: int
    advancer_ratio: float
    amount_ratio_5d: float | None = None


@dataclass(frozen=True)
class IndustryStrengthRankingResult:
    trade_date: str
    return_method: str
    top: list[IndustryPerformance]
    bottom: list[IndustryPerformance]
    volume_leaders: list[IndustryPerformance]
    breadth: dict[str, Any]
