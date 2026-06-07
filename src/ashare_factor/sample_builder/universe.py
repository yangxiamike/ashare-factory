from __future__ import annotations

from pathlib import Path

from ashare_factor.models import SampleConfig, load_yaml_like


DEFAULT_UNIVERSE_PATH = Path("configs/universe.yaml")


def load_universe_config(
    path: str | Path = DEFAULT_UNIVERSE_PATH,
    universe_name: str | None = None,
) -> SampleConfig:
    payload = load_yaml_like(path)
    default_universe = universe_name or payload.get("default_universe")
    universes = payload.get("universes", {})
    if not default_universe or default_universe not in universes:
        raise ValueError(f"Universe config not found: {default_universe!r}")
    raw = universes[default_universe]
    horizons = tuple(sorted(int(item) for item in raw.get("forward_horizons", [1, 3, 5, 10, 20])))
    return SampleConfig(
        universe_name=default_universe,
        require_main_board=bool(raw.get("require_main_board", True)),
        exclude_st=bool(raw.get("exclude_st", True)),
        min_listing_days=int(raw.get("min_listing_days", 60)),
        min_amount=float(raw.get("min_amount", 1_000_000.0)),
        new_stock_window_days=int(raw.get("new_stock_window_days", 20)),
        forward_horizons=horizons,
        min_cross_section_count=int(raw.get("min_cross_section_count", 30)),
    )


def build_base_eligibility_sql(config: SampleConfig) -> str:
    conditions = [
        "NOT COALESCE(is_suspended, FALSE)",
        "COALESCE(total_mv, 0) > 0",
        f"COALESCE(amount, 0) >= {config.min_amount}",
        f"listed_trade_days >= {config.min_listing_days}",
    ]
    if config.require_main_board:
        conditions.append("is_main_board")
    if config.exclude_st:
        conditions.append("NOT is_st")
    if config.new_stock_window_days > 0:
        conditions.append(f"listed_trade_days > {config.new_stock_window_days}")
    return " AND ".join(conditions)
