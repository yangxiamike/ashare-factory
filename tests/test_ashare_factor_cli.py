from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from typer.testing import CliRunner

from ashare_factor.cli import app


runner = CliRunner()


def _patch_cli_settings(monkeypatch, tmp_path: Path) -> None:
    class FakeSettings:
        def __init__(self, duckdb_path: Path | None = None):
            self.duckdb_path = duckdb_path or tmp_path / "missing.duckdb"

        def resolve_paths(self):
            return self

    monkeypatch.setattr("ashare_factor.cli.Settings", FakeSettings)


def test_list_factors_outputs_registry_entries(monkeypatch) -> None:
    def fake_resolve(name: str):
        assert name == "load_factor_registry"
        return lambda **_: [
            {"factor_id": "momentum_20d_v1", "direction": "positive", "status": "candidate"},
            {"factor_id": "reversal_5d_v1", "direction": "negative", "status": "candidate"},
        ]

    monkeypatch.setattr("ashare_factor.cli._resolve_public_function", fake_resolve)

    result = runner.invoke(app, ["list-factors"])

    assert result.exit_code == 0
    assert "Registered factors: 2" in result.stdout
    assert "momentum_20d_v1\tpositive\tcandidate" in result.stdout
    assert "reversal_5d_v1\tnegative\tcandidate" in result.stdout


def test_validate_registry_success(monkeypatch, tmp_path: Path) -> None:
    _patch_cli_settings(monkeypatch, tmp_path)

    def fake_resolve(name: str):
        mapping = {
            "load_factor_registry": lambda **_: [{"factor_id": "momentum_20d_v1"}],
            "validate_registry": lambda **_: [],
        }
        return mapping[name]

    monkeypatch.setattr("ashare_factor.cli._resolve_public_function", fake_resolve)

    result = runner.invoke(app, ["validate-registry"])

    assert result.exit_code == 0
    assert "Registry valid:" in result.stdout


def test_validate_registry_failure_is_friendly(monkeypatch, tmp_path: Path) -> None:
    _patch_cli_settings(monkeypatch, tmp_path)

    def fake_resolve(name: str):
        mapping = {
            "load_factor_registry": lambda **_: [{"factor_id": "broken_factor"}],
            "validate_registry": lambda **_: ["duplicate factor_id: broken_factor", "invalid direction: sideways"],
        }
        return mapping[name]

    monkeypatch.setattr("ashare_factor.cli._resolve_public_function", fake_resolve)

    result = runner.invoke(app, ["validate-registry"])

    assert result.exit_code == 1
    assert "Registry validation failed:" in result.stderr
    assert "- duplicate factor_id: broken_factor" in result.stderr
    assert "- invalid direction: sideways" in result.stderr


def test_evaluate_factor_runs_pipeline(monkeypatch, tmp_path: Path) -> None:
    _patch_cli_settings(monkeypatch, tmp_path)
    calls: list[str] = []

    def fake_resolve(name: str):
        def load_factor_registry(**kwargs):
            calls.append(f"load:{kwargs['registry_path']}")
            return [{"factor_id": "momentum_20d_v1", "direction": "positive", "status": "candidate"}]

        def build_sample(**kwargs):
            calls.append(f"sample:{kwargs['start_date']}:{kwargs['end_date']}")
            return SimpleNamespace(
                sample=pd.DataFrame({"trade_date": pd.to_datetime(["2024-01-02"]), "ts_code": ["A"]})
            )

        def calculate_factor(**kwargs):
            calls.append(f"calculate:{kwargs['factor']['factor_id']}")
            return pd.DataFrame(
                {
                    "trade_date": pd.to_datetime(["2024-01-02"]),
                    "ts_code": ["A"],
                    "factor_value_raw": [1.0],
                }
            )

        def preprocess_factor(**kwargs):
            calls.append("preprocess")
            return pd.DataFrame(
                {
                    "trade_date": pd.to_datetime(["2024-01-02"]),
                    "ts_code": ["A"],
                    "factor_value_raw": [1.0],
                    "factor_value_processed": [1.0],
                }
            )

        def evaluate_factor(**kwargs):
            calls.append(f"evaluate:{kwargs['factor_spec']['factor_id']}")
            return {
                "factor_id": "momentum_20d_v1",
                "gate_decision": {"status": "watch", "reasons": ["insufficient OOS history"]},
                "output_paths": {},
            }

        def write_evaluation_report(**kwargs):
            calls.append("report")
            return tmp_path / "reports" / "factor_evaluation" / "momentum.md"

        def update_factor_library(**kwargs):
            calls.append("library")
            return {"library_path": str(tmp_path / "outputs" / "factor_library" / "factor_library.json")}

        mapping = {
            "load_factor_registry": load_factor_registry,
            "build_sample": build_sample,
            "calculate_factor": calculate_factor,
            "preprocess_factor": preprocess_factor,
            "evaluate_factor": evaluate_factor,
            "write_evaluation_report": write_evaluation_report,
            "update_factor_library": update_factor_library,
        }
        return mapping[name]

    monkeypatch.setattr("ashare_factor.cli._resolve_public_function", fake_resolve)

    result = runner.invoke(
        app,
        [
            "evaluate-factor",
            "--factor-id",
            "momentum_20d_v1",
            "--start-date",
            "20240101",
            "--end-date",
            "20240131",
            "--output-root",
            str(tmp_path / "outputs"),
            "--report-root",
            str(tmp_path / "reports" / "factor_evaluation"),
            "--library-path",
            str(tmp_path / "outputs" / "factor_library" / "factor_library.json"),
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        f"load:{Path.cwd() / 'configs' / 'factor_registry.yaml'}",
        "sample:20240101:20240131",
        "calculate:momentum_20d_v1",
        "preprocess",
        "evaluate:momentum_20d_v1",
        "report",
        "library",
    ]
    assert "Evaluated factor: momentum_20d_v1" in result.stdout
    assert "Gate status: watch" in result.stdout
    assert "insufficient OOS history" in result.stdout


def test_evaluate_all_runs_every_factor(monkeypatch, tmp_path: Path) -> None:
    evaluated: list[str] = []

    def fake_run_pipeline(factor_id: str, **kwargs):
        evaluated.append(factor_id)
        return (
            {"status": "watch", "result_path": str(tmp_path / f"{factor_id}.json")},
            {"status": "watch", "reasons": []},
            tmp_path / f"{factor_id}.md",
            {"library_path": str(tmp_path / "factor_library.json")},
        )

    monkeypatch.setattr("ashare_factor.cli._run_factor_pipeline", fake_run_pipeline)
    monkeypatch.setattr(
        "ashare_factor.cli._resolve_public_function",
        lambda name: (lambda **_: [{"factor_id": "f1"}, {"factor_id": "f2"}]) if name == "load_factor_registry" else None,
    )

    result = runner.invoke(app, ["evaluate-all"])

    assert result.exit_code == 0
    assert evaluated == ["f1", "f2"]
    assert "==> f1" in result.stdout
    assert "==> f2" in result.stdout


def test_show_result_reads_factor_library(tmp_path: Path) -> None:
    library_path = tmp_path / "outputs" / "factor_library" / "factor_library.json"
    library_path.parent.mkdir(parents=True)
    library_path.write_text(
        '{"factors":{"momentum_20d_v1":{"status":"watch","mean_rank_ic":0.031,"ic_ir":0.48,"coverage_pct":0.82,"reasons":["OOS window still short"]}}}',
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "show-result",
            "--factor-id",
            "momentum_20d_v1",
            "--library-path",
            str(library_path),
        ],
    )

    assert result.exit_code == 0
    assert f"Library file: {library_path}" in result.stdout
    assert "Gate status: watch" in result.stdout
    assert "mean_rank_ic: 0.031" in result.stdout
    assert "- OOS window still short" in result.stdout


def test_missing_public_api_reports_clean_error() -> None:
    def fake_resolve(name: str):
        raise RuntimeError(f"missing required factor factory API: {name}")

    from ashare_factor import cli

    original = cli._resolve_public_function
    cli._resolve_public_function = fake_resolve
    try:
        result = runner.invoke(app, ["list-factors"])
    finally:
        cli._resolve_public_function = original

    assert result.exit_code == 1
    assert "missing required factor factory API: load_factor_registry" in result.stderr
