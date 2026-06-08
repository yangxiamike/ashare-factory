from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from ashare_radar.models import StyleBucketConfig, StyleBucketPerformance, StyleFactorRankingResult

DEFAULT_STYLE_CONFIG_PATH = Path("configs") / "ashare_radar" / "style_buckets.yaml"

DEFAULT_STYLE_BUCKETS: dict[str, StyleBucketConfig] = {
    "size": StyleBucketConfig(
        factor_name="size",
        field="total_mv",
        side="high",
        top_label="large_cap",
        bottom_label="small_cap",
    ),
    "valuation": StyleBucketConfig(
        factor_name="valuation",
        field="pb",
        side="low",
        top_label="value",
        bottom_label="expensive",
    ),
    "dividend": StyleBucketConfig(
        factor_name="dividend",
        field="dv_ratio",
        side="high",
        top_label="high_dividend",
        bottom_label="low_dividend",
    ),
    "turnover": StyleBucketConfig(
        factor_name="turnover",
        field="turnover_rate",
        side="high",
        top_label="high_turnover",
        bottom_label="low_turnover",
    ),
    "price": StyleBucketConfig(
        factor_name="price",
        field="close",
        side="low",
        top_label="low_price",
        bottom_label="high_price",
    ),
}


def load_style_bucket_configs(config_path: str | Path = DEFAULT_STYLE_CONFIG_PATH) -> dict[str, StyleBucketConfig]:
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    styles = payload.get("styles")
    if not isinstance(styles, dict) or not styles:
        raise ValueError(f"style config must define a non-empty styles mapping: {config_path}")

    return {
        style_name: StyleBucketConfig(
            factor_name=str(config.get("factor_name", style_name)),
            field=str(config["field"]),
            side=str(config["side"]),
            quantile=float(config.get("quantile", 0.2)),
            top_label=str(config.get("top_label", "top")),
            bottom_label=str(config.get("bottom_label", "bottom")),
        )
        for style_name, config in styles.items()
    }


def rank_style_factors(
    daily_panel: pd.DataFrame,
    trade_date: str,
    style_configs: dict[str, StyleBucketConfig] | None = None,
) -> StyleFactorRankingResult:
    current = daily_panel.loc[daily_panel["trade_date"] == trade_date].copy()
    if current.empty:
        raise ValueError(f"no daily_panel rows found for trade_date={trade_date}")

    active = current.loc[~current["is_suspended"].fillna(False)].copy()
    configs = style_configs or load_style_bucket_configs()
    rankings: list[StyleBucketPerformance] = []

    for config in configs.values():
        if config.field not in active.columns:
            raise ValueError(f"style field not found in panel: {config.field}")
        scored = active[["pct_chg", config.field]].dropna().copy()
        if scored.empty:
            continue
        bucket_size = max(int(len(scored) * config.quantile), 1)
        ordered = scored.sort_values(config.field, ascending=(config.side == "low"))
        top_bucket = ordered.head(bucket_size)
        bottom_bucket = ordered.tail(bucket_size)
        rankings.append(_build_bucket_result(config, config.top_label, top_bucket))
        rankings.append(_build_bucket_result(config, config.bottom_label, bottom_bucket))

    rankings.sort(key=lambda item: item.mean_return, reverse=True)
    return StyleFactorRankingResult(trade_date=trade_date, rankings=rankings, config=configs)


def _build_bucket_result(
    config: StyleBucketConfig,
    bucket_name: str,
    frame: pd.DataFrame,
) -> StyleBucketPerformance:
    return StyleBucketPerformance(
        factor_name=config.factor_name,
        bucket_name=bucket_name,
        mean_return=float(frame["pct_chg"].mean()),
        median_return=float(frame["pct_chg"].median()),
        stock_count=int(len(frame)),
        field=config.field,
        side=config.side,
    )
