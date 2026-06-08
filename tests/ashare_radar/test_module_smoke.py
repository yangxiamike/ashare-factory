from __future__ import annotations

import importlib


def test_news_intake_module_exports_pipeline() -> None:
    module = importlib.import_module("ashare_radar.news_intake")
    assert callable(module.build_news_digest)
    assert callable(module.clean_news_items)
    assert callable(module.dedup_news_items)
    assert callable(module.filter_relevant_news)
    assert callable(module.structure_news_items)
    assert callable(module.rank_news_items)


def test_cli_module_exports_app() -> None:
    module = importlib.import_module("ashare_radar.cli")
    assert module.app is not None


def test_core_modules_export_expected_entrypoints() -> None:
    radar = importlib.import_module("ashare_radar")
    assert callable(radar.validate_daily_panel_columns)
    assert callable(radar.load_daily_panel)
    assert callable(radar.load_daily_panel_window)
    assert callable(radar.compute_market_temperature)
    assert callable(radar.rank_style_factors)
    assert callable(radar.rank_industries)
    assert callable(radar.render_daily_report)
