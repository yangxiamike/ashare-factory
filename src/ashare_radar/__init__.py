"""A-share market radar core package."""

from ashare_radar.data_input import (
    DAILY_PANEL_REQUIRED_COLUMNS,
    daily_panel_coverage,
    load_daily_panel,
    load_daily_panel_window,
    validate_daily_panel_columns,
)
from ashare_radar.industry_strength_ranking import rank_industries, rank_industry_strength
from ashare_radar.market_temperature import compute_market_temperature, evaluate_market_temperature
from ashare_radar.models import (
    IndustryPerformance,
    IndustryStrengthRankingResult,
    MarketTemperatureResult,
    StyleBucketConfig,
    StyleBucketPerformance,
    StyleFactorRankingResult,
)
from ashare_radar.report_generator import generate_market_radar_report, render_daily_report, write_daily_report
from ashare_radar.style_factor_ranking import (
    DEFAULT_STYLE_BUCKETS,
    DEFAULT_STYLE_CONFIG_PATH,
    load_style_bucket_configs,
    rank_style_factors,
)

__all__ = [
    "DAILY_PANEL_REQUIRED_COLUMNS",
    "DEFAULT_STYLE_BUCKETS",
    "DEFAULT_STYLE_CONFIG_PATH",
    "IndustryPerformance",
    "IndustryStrengthRankingResult",
    "MarketTemperatureResult",
    "StyleBucketConfig",
    "StyleBucketPerformance",
    "StyleFactorRankingResult",
    "compute_market_temperature",
    "daily_panel_coverage",
    "evaluate_market_temperature",
    "generate_market_radar_report",
    "load_style_bucket_configs",
    "load_daily_panel",
    "load_daily_panel_window",
    "rank_industry_strength",
    "rank_industries",
    "rank_style_factors",
    "render_daily_report",
    "validate_daily_panel_columns",
    "write_daily_report",
]

__version__ = "0.1.0"
