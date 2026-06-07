from __future__ import annotations

import inspect
import json
from importlib import import_module
from pathlib import Path
from typing import Any, Iterable

import typer
import yaml

from ashare_data.config import Settings
from ashare_factor.data_access import get_daily_panel_columns
from ashare_factor.models import EvaluationConfig, PreprocessConfig, SampleConfig
from ashare_factor.sample_builder.universe import load_universe_config

app = typer.Typer(help="A-share factor factory CLI.")

_PUBLIC_API_MODULES: dict[str, tuple[str, ...]] = {
    "load_factor_registry": ("ashare_factor.factor_research.registry",),
    "validate_registry": ("ashare_factor.factor_research.registry",),
    "build_sample": ("ashare_factor.sample_builder.sample",),
    "calculate_factor": ("ashare_factor.factor_research.calculator",),
    "preprocess_factor": ("ashare_factor.factor_research.preprocessing",),
    "evaluate_factor": ("ashare_factor.factor_evaluation.evaluator",),
    "apply_gate": ("ashare_factor.factor_evaluation.gate",),
    "update_factor_library": ("ashare_factor.factor_evaluation.library",),
    "write_evaluation_report": ("ashare_factor.factor_evaluation.report",),
}


def _fail(exc: Exception | str) -> None:
    message = str(exc)
    typer.secho(f"ERROR: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _project_root() -> Path:
    return Path.cwd()


def _resolve_public_function(name: str):
    package = import_module("ashare_factor")
    candidate = getattr(package, name, None)
    if callable(candidate):
        return candidate

    for module_name in _PUBLIC_API_MODULES.get(name, ()):
        try:
            module = import_module(module_name)
        except ModuleNotFoundError:
            continue
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate

    raise RuntimeError(
        f"missing required factor factory API: {name}. "
        "Please merge Worker A/B factor factory modules before using this CLI."
    )


def _call_public(name: str, **kwargs: Any) -> Any:
    fn = _resolve_public_function(name)
    signature = inspect.signature(fn)
    accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())
    if accepts_kwargs:
        return fn(**kwargs)

    filtered_kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
    return fn(**filtered_kwargs)


def _coerce_registry_entries(registry: Any) -> list[Any]:
    if registry is None:
        return []
    if isinstance(registry, dict):
        for key in ("factors", "items", "registry"):
            value = registry.get(key)
            if isinstance(value, list):
                return value
        return list(registry.values())
    if isinstance(registry, list):
        return registry
    if isinstance(registry, tuple):
        return list(registry)
    if hasattr(registry, "factors"):
        return list(getattr(registry, "factors"))
    raise RuntimeError("unsupported factor registry format")


def _get_value(obj: Any, field: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _find_factor_spec(registry: Any, factor_id: str) -> Any:
    if isinstance(registry, dict) and factor_id in registry:
        return registry[factor_id]
    for item in _coerce_registry_entries(registry):
        if _get_value(item, "factor_id") == factor_id:
            return item
    raise RuntimeError(f"factor_id not found in registry: {factor_id}")


def _normalize_validation_errors(result: Any) -> list[str]:
    if result is None or result is True:
        return []
    if result is False:
        return ["registry validation failed"]
    if isinstance(result, str):
        return [result]
    if isinstance(result, list):
        return [str(item) for item in result]
    if isinstance(result, tuple):
        return [str(item) for item in result]
    if isinstance(result, dict):
        errors = result.get("errors")
        if errors is None:
            return []
        if isinstance(errors, (list, tuple)):
            return [str(item) for item in errors]
        return [str(errors)]
    if hasattr(result, "errors"):
        errors = getattr(result, "errors")
        if errors is None:
            return []
        if isinstance(errors, (list, tuple)):
            return [str(item) for item in errors]
        return [str(errors)]
    return []


def _iter_output_paths(*values: Any) -> Iterable[Path]:
    seen: set[Path] = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, (str, Path)):
            path = Path(value)
            if path not in seen:
                seen.add(path)
                yield path
            continue
        if isinstance(value, dict):
            candidates = [
                value.get("result_path"),
                value.get("report_path"),
                value.get("library_path"),
                value.get("output_path"),
                value.get("path"),
            ]
            output_paths = value.get("output_paths")
            if isinstance(output_paths, dict):
                candidates.extend(output_paths.values())
        else:
            candidates = [
                getattr(value, "result_path", None),
                getattr(value, "report_path", None),
                getattr(value, "library_path", None),
                getattr(value, "output_path", None),
                getattr(value, "path", None),
            ]
            output_paths = getattr(value, "output_paths", None)
            if isinstance(output_paths, dict):
                candidates.extend(output_paths.values())
        for candidate in candidates:
            if candidate is None:
                continue
            path = Path(candidate)
            if path not in seen:
                seen.add(path)
                yield path


def _default_registry_path() -> Path:
    return _project_root() / "configs" / "factor_registry.yaml"


def _default_universe_path() -> Path:
    return _project_root() / "configs" / "universe.yaml"


def _default_evaluation_path() -> Path:
    return _project_root() / "configs" / "evaluation.yaml"


def _default_output_root() -> Path:
    return _project_root() / "outputs"


def _default_report_root() -> Path:
    return _project_root() / "reports" / "factor_evaluation"


def _default_library_path() -> Path:
    return _default_output_root() / "factor_library" / "factor_library.json"


def _emit_result_summary(
    factor_id: str,
    evaluation_result: Any,
    gate_decision: Any,
    report_output: Any,
    library_output: Any,
) -> None:
    status = _get_value(gate_decision, "status") or _get_value(evaluation_result, "status") or "unknown"
    typer.echo(f"Evaluated factor: {factor_id}")
    typer.echo(f"Gate status: {status}")

    reasons = _get_value(gate_decision, "reasons") or _get_value(evaluation_result, "reasons") or []
    if reasons:
        for reason in reasons:
            typer.echo(f"- {reason}")

    for path in _iter_output_paths(evaluation_result, gate_decision, report_output, library_output):
        typer.echo(f"Output: {path}")


def _run_factor_pipeline(
    factor_id: str,
    *,
    start_date: str | None,
    end_date: str | None,
    registry_path: Path,
    universe_path: Path,
    evaluation_path: Path,
    duckdb_path: Path | None,
    output_root: Path,
    report_root: Path,
    library_path: Path,
) -> tuple[Any, Any, Any, Any]:
    sample_config = _load_sample_config(universe_path, start_date=start_date, end_date=end_date)
    evaluation_config = _load_evaluation_config(
        evaluation_path,
        output_root=output_root,
        report_root=report_root,
    )
    settings = Settings(duckdb_path=duckdb_path).resolve_paths()
    available_columns = get_daily_panel_columns(settings.duckdb_path) if settings.duckdb_path.exists() else None
    registry = _call_public(
        "load_factor_registry",
        path=registry_path,
        registry_path=registry_path,
        available_columns=available_columns,
    )
    factor_spec = _find_factor_spec(registry, factor_id)
    sample_result = _call_public(
        "build_sample",
        start_date=start_date,
        end_date=end_date,
        config=sample_config,
        settings=settings,
    )
    factor_raw = _call_public("calculate_factor", factor=factor_spec, sample=sample_result)
    factor_processed = _call_public(
        "preprocess_factor",
        factor_values=factor_raw,
        sample=sample_result,
        config=evaluation_config,
    )
    eval_frame = factor_processed.merge(
        sample_result.sample,
        on=["trade_date", "ts_code"],
        how="inner",
        validate="one_to_one",
    )
    evaluation_result = _call_public(
        "evaluate_factor",
        factor_df=eval_frame,
        factor_spec=factor_spec,
        evaluation_config=evaluation_config,
        duckdb_path=settings.duckdb_path,
        registry_path=registry_path,
        universe_path=universe_path,
        evaluation_path=evaluation_path,
        output_root=output_root,
    )
    report_output = _call_public("write_evaluation_report", eval_result=evaluation_result)
    library_output = _call_public("update_factor_library", eval_result=evaluation_result, library_path=library_path)
    return evaluation_result, evaluation_result.get("gate_decision", {}), report_output, library_output


def _load_sample_config(path: Path, *, start_date: str | None, end_date: str | None) -> SampleConfig:
    base = load_universe_config(path)
    return SampleConfig(
        universe_name=base.universe_name,
        start_date=start_date,
        end_date=end_date,
        require_main_board=base.require_main_board,
        exclude_st=base.exclude_st,
        min_listing_days=base.min_listing_days,
        min_amount=base.min_amount,
        new_stock_window_days=base.new_stock_window_days,
        forward_horizons=base.forward_horizons,
        min_cross_section_count=base.min_cross_section_count,
    )


def _load_evaluation_config(path: Path, *, output_root: Path, report_root: Path) -> EvaluationConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    evaluation = data.get("evaluation", {})
    preprocess = data.get("preprocess", {})
    winsorize = preprocess.get("winsorize", {})
    return EvaluationConfig(
        preprocess=PreprocessConfig(
            winsorize_method=str(winsorize.get("method", "mad")),
            winsorize_n_mad=float(winsorize.get("n_mad", 3.0)),
            neutralize=str(preprocess.get("neutralize", "industry_size")),
            re_standardize_after_neutralize=bool(preprocess.get("re_standardize_after_neutralize", True)),
        ),
        evaluation=evaluation,
        gate=data.get("gate", {}),
        output_root=output_root,
        report_root=report_root,
    )


@app.command("list-factors")
def list_factors(
    registry_path: Path = typer.Option(_default_registry_path(), "--registry-path", help="Path to factor_registry.yaml."),
) -> None:
    """List factors registered in factor_registry.yaml."""
    try:
        registry = _call_public("load_factor_registry", path=registry_path, registry_path=registry_path)
        items = _coerce_registry_entries(registry)
        typer.echo(f"Registered factors: {len(items)}")
        for item in items:
            factor_id = _get_value(item, "factor_id", "<missing>")
            direction = _get_value(item, "direction", "-")
            status = _get_value(item, "status", "-")
            typer.echo(f"{factor_id}\t{direction}\t{status}")
    except Exception as exc:
        _fail(exc)


@app.command("validate-registry")
def validate_registry_cmd(
    registry_path: Path = typer.Option(_default_registry_path(), "--registry-path", help="Path to factor_registry.yaml."),
) -> None:
    """Validate the factor registry schema and builtin references."""
    try:
        settings = Settings().resolve_paths()
        available_columns = get_daily_panel_columns(settings.duckdb_path) if settings.duckdb_path.exists() else None
        registry = _call_public(
            "load_factor_registry",
            path=registry_path,
            registry_path=registry_path,
            available_columns=available_columns,
        )
        result = _call_public(
            "validate_registry",
            registry=registry,
            path=registry_path,
            registry_path=registry_path,
            available_columns=available_columns,
        )
        errors = _normalize_validation_errors(result)
        if errors:
            typer.secho("Registry validation failed:", fg=typer.colors.RED, err=True)
            for error in errors:
                typer.echo(f"- {error}", err=True)
            raise typer.Exit(code=1)
        typer.echo(f"Registry valid: {registry_path}")
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@app.command("evaluate-factor")
def evaluate_factor_cmd(
    factor_id: str = typer.Option(..., "--factor-id", help="Registered factor identifier."),
    start_date: str | None = typer.Option(None, "--start-date", help="Inclusive start date, format YYYYMMDD."),
    end_date: str | None = typer.Option(None, "--end-date", help="Inclusive end date, format YYYYMMDD."),
    registry_path: Path = typer.Option(_default_registry_path(), "--registry-path", help="Path to factor_registry.yaml."),
    universe_path: Path = typer.Option(_default_universe_path(), "--universe-path", help="Path to universe.yaml."),
    evaluation_path: Path = typer.Option(
        _default_evaluation_path(),
        "--evaluation-path",
        help="Path to evaluation.yaml.",
    ),
    duckdb_path: Path | None = typer.Option(None, "--duckdb-path", help="Path to DuckDB warehouse."),
    output_root: Path = typer.Option(
        _default_output_root(),
        "--output-root",
        "--result-root",
        help="Root directory for factor-factory outputs. `--result-root` is kept as a legacy alias.",
    ),
    report_root: Path = typer.Option(
        _default_report_root(),
        "--report-root",
        help="Directory for Markdown evaluation reports.",
    ),
    library_path: Path = typer.Option(
        _default_library_path(),
        "--library-path",
        help="Path to factor_library.json.",
    ),
) -> None:
    """Run the full single-factor factor-factory pipeline."""
    try:
        evaluation_result, gate_decision, report_output, library_output = _run_factor_pipeline(
            factor_id,
            start_date=start_date,
            end_date=end_date,
            registry_path=registry_path,
            universe_path=universe_path,
            evaluation_path=evaluation_path,
            duckdb_path=duckdb_path,
            output_root=output_root,
            report_root=report_root,
            library_path=library_path,
        )
        _emit_result_summary(factor_id, evaluation_result, gate_decision, report_output, library_output)
    except Exception as exc:
        _fail(exc)


@app.command("evaluate-all")
def evaluate_all_cmd(
    start_date: str | None = typer.Option(None, "--start-date", help="Inclusive start date, format YYYYMMDD."),
    end_date: str | None = typer.Option(None, "--end-date", help="Inclusive end date, format YYYYMMDD."),
    registry_path: Path = typer.Option(_default_registry_path(), "--registry-path", help="Path to factor_registry.yaml."),
    universe_path: Path = typer.Option(_default_universe_path(), "--universe-path", help="Path to universe.yaml."),
    evaluation_path: Path = typer.Option(
        _default_evaluation_path(),
        "--evaluation-path",
        help="Path to evaluation.yaml.",
    ),
    duckdb_path: Path | None = typer.Option(None, "--duckdb-path", help="Path to DuckDB warehouse."),
    output_root: Path = typer.Option(
        _default_output_root(),
        "--output-root",
        "--result-root",
        help="Root directory for factor-factory outputs. `--result-root` is kept as a legacy alias.",
    ),
    report_root: Path = typer.Option(
        _default_report_root(),
        "--report-root",
        help="Directory for Markdown evaluation reports.",
    ),
    library_path: Path = typer.Option(
        _default_library_path(),
        "--library-path",
        help="Path to factor_library.json.",
    ),
) -> None:
    """Run the factor-factory pipeline for all registered factors."""
    try:
        registry = _call_public("load_factor_registry", path=registry_path, registry_path=registry_path)
        items = _coerce_registry_entries(registry)
        if not items:
            typer.echo("No registered factors found.")
            return

        for item in items:
            factor_id = _get_value(item, "factor_id", "<missing>")
            typer.echo(f"==> {factor_id}")
            evaluation_result, gate_decision, report_output, library_output = _run_factor_pipeline(
                factor_id,
                start_date=start_date,
                end_date=end_date,
                registry_path=registry_path,
                universe_path=universe_path,
                evaluation_path=evaluation_path,
                duckdb_path=duckdb_path,
                output_root=output_root,
                report_root=report_root,
                library_path=library_path,
            )
            _emit_result_summary(factor_id, evaluation_result, gate_decision, report_output, library_output)
    except Exception as exc:
        _fail(exc)


@app.command("show-result")
def show_result_cmd(
    factor_id: str = typer.Option(..., "--factor-id", help="Factor identifier."),
    library_path: Path = typer.Option(
        _default_library_path(),
        "--library-path",
        help="Path to factor_library.json.",
    ),
) -> None:
    """Show the latest saved factor summary for a factor."""
    try:
        if not library_path.exists():
            raise RuntimeError(f"factor library not found: {library_path}")
        payload = json.loads(library_path.read_text(encoding="utf-8"))
        entry = payload.get("factors", {}).get(factor_id)
        if not entry:
            raise RuntimeError(f"no saved factor summary found for {factor_id} in {library_path}")

        typer.echo(f"Library file: {library_path}")

        status = entry.get("status")
        if status:
            typer.echo(f"Gate status: {status}")

        summary_fields = ("mean_rank_ic", "ic_ir", "coverage_pct", "long_short_sharpe")
        for field in summary_fields:
            if field in entry:
                typer.echo(f"{field}: {entry[field]}")

        reasons = entry.get("reasons", [])
        if reasons:
            for reason in reasons:
                typer.echo(f"- {reason}")
    except Exception as exc:
        _fail(exc)


if __name__ == "__main__":
    app()
