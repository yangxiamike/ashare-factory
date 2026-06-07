from __future__ import annotations

import pandas as pd

from ashare_factor.factor_research.builtins import calculate_builtin_factor
from ashare_factor.models import FactorSpec, SampleResult


def calculate_factor(
    factor: FactorSpec | str,
    sample: SampleResult | pd.DataFrame,
    *,
    registry: dict[str, FactorSpec] | None = None,
) -> pd.DataFrame:
    sample_frame = sample.sample if isinstance(sample, SampleResult) else sample
    if isinstance(factor, str):
        if registry is None:
            raise ValueError("registry is required when factor is passed as a factor_id")
        spec = registry[factor]
    else:
        spec = factor

    if spec.implementation.startswith("builtin:"):
        return calculate_builtin_factor(sample_frame, spec)
    raise ValueError(f"Unsupported factor implementation: {spec.implementation}")
