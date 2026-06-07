from __future__ import annotations

from pathlib import Path

from ashare_factor.factor_research.builtins import builtin_factor_ids
from ashare_factor.models import DAILY_PANEL_FIELDS, FactorSpec, load_yaml_like


DEFAULT_REGISTRY_PATH = Path("configs/factor_registry.yaml")
REQUIRED_FIELDS = {
    "factor_id",
    "factor_name",
    "category",
    "formula_text",
    "implementation",
    "params",
    "direction",
    "lookback_days",
    "data_fields",
    "status",
    "description",
    "hypothesis",
}


def load_factor_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, FactorSpec]:
    payload = load_yaml_like(path)
    factors = payload.get("factors", [])
    registry: dict[str, FactorSpec] = {}
    builtin_ids = builtin_factor_ids()
    for index, raw in enumerate(factors, start=1):
        missing = REQUIRED_FIELDS - raw.keys()
        if missing:
            raise ValueError(f"Factor #{index} missing required fields: {sorted(missing)}")
        factor_id = str(raw["factor_id"])
        if factor_id in registry:
            raise ValueError(f"Duplicate factor_id in registry: {factor_id}")
        direction = str(raw["direction"])
        if direction not in {"positive", "negative"}:
            raise ValueError(f"{factor_id}: direction must be positive or negative")
        status = str(raw["status"])
        if status != "candidate":
            raise ValueError(f"{factor_id}: registry status must stay candidate")
        implementation = str(raw["implementation"])
        if implementation.startswith("builtin:") and implementation not in builtin_ids:
            raise ValueError(f"{factor_id}: builtin implementation not found: {implementation}")
        invalid_fields = sorted(set(raw["data_fields"]) - DAILY_PANEL_FIELDS)
        if invalid_fields:
            raise ValueError(f"{factor_id}: unknown daily_panel fields: {invalid_fields}")
        registry[factor_id] = FactorSpec(
            factor_id=factor_id,
            factor_name=str(raw["factor_name"]),
            category=str(raw["category"]),
            formula_text=str(raw["formula_text"]),
            implementation=implementation,
            params=dict(raw["params"]),
            direction=direction,
            lookback_days=int(raw["lookback_days"]),
            data_fields=[str(item) for item in raw["data_fields"]],
            status=status,
            description=str(raw["description"]),
            hypothesis=str(raw["hypothesis"]),
        )
    return registry


def validate_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> list[str]:
    try:
        load_factor_registry(path)
    except Exception as exc:
        return [str(exc)]
    return []


def get_factor(factor_id: str, registry: dict[str, FactorSpec] | None = None) -> FactorSpec:
    factor_registry = registry or load_factor_registry()
    try:
        return factor_registry[factor_id]
    except KeyError as exc:
        raise KeyError(f"Factor not found in registry: {factor_id}") from exc
