from __future__ import annotations

from typing import Any

from .metrics import sanitize_for_json, to_plain_dict


def apply_gate(eval_result: dict[str, Any] | Any, config: dict[str, Any] | Any) -> dict[str, Any]:
    result = to_plain_dict(eval_result)
    cfg = to_plain_dict(config)
    gate_cfg = cfg.get("gate", cfg)
    validity_cfg = gate_cfg.get("validity_gate", {})
    research_cfg = gate_cfg.get("research_evidence_gate", {})
    library_cfg = gate_cfg.get("library_decision_gate", {})

    full_sample = result.get("metrics", {}).get("full_sample", {})
    validity_reasons: list[str] = []
    validity_passed = True

    if result.get("validity_checks", {}).get("all_nan"):
        validity_passed = False
        validity_reasons.append("calculation yielded all NaN")
    if result.get("validity_checks", {}).get("constant_factor"):
        validity_passed = False
        validity_reasons.append("constant factor values")

    coverage_pct = full_sample.get("coverage_pct", 0.0) or 0.0
    n_valid_dates = full_sample.get("n_valid_dates", 0) or 0
    n_forward_samples = full_sample.get("n_forward_return_samples", 0) or 0

    if coverage_pct < validity_cfg.get("min_coverage_pct", 0.30):
        validity_passed = False
        validity_reasons.append(f"coverage too low: {coverage_pct:.2%}")
    if n_valid_dates < validity_cfg.get("min_valid_dates", 60):
        validity_passed = False
        validity_reasons.append(f"valid dates too few: {n_valid_dates}")
    if n_forward_samples < validity_cfg.get("min_forward_return_samples", 1000):
        validity_passed = False
        validity_reasons.append(f"forward return samples too few: {n_forward_samples}")

    validity_conclusion = {
        "passed": validity_passed,
        "status": "passed" if validity_passed else validity_cfg.get("fail_status", "invalid"),
        "reasons": validity_reasons,
    }
    if not validity_passed:
        return sanitize_for_json(
            {
                "status": validity_cfg.get("fail_status", "invalid"),
                "reasons": validity_reasons,
                "validity": validity_conclusion,
                "research_evidence": {"passed": False, "status": "not_run", "reasons": ["validity gate failed"]},
                "library_decision": {"passed": False, "status": "not_run", "reasons": ["validity gate failed"]},
            }
        )

    research_evidence = _evaluate_research_gate(full_sample, research_cfg)
    if not research_evidence["passed"]:
        return sanitize_for_json(
            {
                "status": research_cfg.get("fail_status", "rejected"),
                "reasons": research_evidence["reasons"],
                "validity": validity_conclusion,
                "research_evidence": research_evidence,
                "library_decision": {
                    "passed": False,
                    "status": "not_run",
                    "reasons": ["research evidence gate failed"],
                },
            }
        )

    library_decision = _evaluate_library_gate(result, library_cfg)
    return sanitize_for_json(
        {
            "status": library_decision["status"],
            "reasons": library_decision["reasons"] or research_evidence["reasons"],
            "validity": validity_conclusion,
            "research_evidence": research_evidence,
            "library_decision": library_decision,
        }
    )


def _evaluate_research_gate(full_sample: dict[str, Any], research_cfg: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    evidence = {}

    rank_ic_mean = full_sample.get("rank_ic", {}).get("mean")
    spread_mean = full_sample.get("quantile", {}).get("q5_q1_spread_mean")
    top_return = full_sample.get("top_quantile", {}).get("mean_return")
    monotonicity = full_sample.get("quantile", {}).get("monotonicity")
    turnover = full_sample.get("turnover", {}).get("mean_turnover")
    max_dd = full_sample.get("top_quantile", {}).get("max_drawdown")

    direction_ok = (rank_ic_mean or 0) > 0 and (spread_mean or 0) > 0
    top_effective = top_return is not None and top_return > 0
    clearly_reversed = monotonicity == "decreasing"
    turnover_uncontrolled = turnover is not None and turnover > 0.80
    drawdown_uncontrolled = max_dd is not None and max_dd < -0.50
    top_clearly_negative = top_return is not None and top_return < 0

    if not direction_ok:
        reasons.append("direction-adjusted RankIC or Q5-Q1 spread is not positive")
    if clearly_reversed:
        reasons.append("quantile structure is clearly reversed")
    if top_clearly_negative:
        reasons.append("top quantile return is clearly negative")
    if turnover_uncontrolled:
        reasons.append("turnover appears uncontrolled")
    if drawdown_uncontrolled:
        reasons.append("top quantile drawdown appears uncontrolled")

    evidence.update(
        {
            "direction_ok": direction_ok,
            "top_quantile_effective": top_effective,
            "quantiles_clearly_reversed": clearly_reversed,
            "turnover_uncontrolled": turnover_uncontrolled,
            "drawdown_uncontrolled": drawdown_uncontrolled,
        }
    )
    passed = not reasons
    return {
        "passed": passed,
        "status": research_cfg.get("default_pass_status", "watch") if passed else research_cfg.get("fail_status", "rejected"),
        "reasons": reasons if reasons else ["basic research evidence present"],
        "evidence": evidence,
    }


def _evaluate_library_gate(result: dict[str, Any], library_cfg: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    full_sample = result.get("metrics", {}).get("full_sample", {})
    in_sample = result.get("oos_evidence", {}).get("in_sample", {})
    oos = result.get("oos_evidence", {}).get("out_of_sample", {})
    baseline = result.get("baseline_comparison", {})
    stability = full_sample.get("stability", {})

    in_sample_direction_correct = (in_sample.get("rank_ic", {}).get("mean") or 0) > 0
    oos_direction_not_reversed = (oos.get("rank_ic", {}).get("mean") or 0) >= 0
    in_sample_q5_q1_positive = (in_sample.get("quantile", {}).get("q5_q1_spread_mean") or 0) > 0
    oos_q5_q1_not_reversed = (oos.get("quantile", {}).get("q5_q1_spread_mean") or 0) >= 0
    top_quantile_return_positive = (full_sample.get("top_quantile", {}).get("mean_return") or 0) > 0

    baseline_summary = baseline.get("summary", {})
    stronger_than_noise = baseline_summary.get("stronger_than_most_noise_baselines")
    not_worse_than_simple = baseline_summary.get("not_worse_than_simple_technical_baselines")

    single_year_flag = stability.get("single_year_concentration", {}).get("has_single_year_concentration")
    turnover = full_sample.get("turnover", {}).get("mean_turnover")
    drawdown = full_sample.get("top_quantile", {}).get("max_drawdown")
    turnover_and_drawdown_ok = not ((turnover is not None and turnover > 0.80) or (drawdown is not None and drawdown < -0.50))

    active_requirements = {
        "evaluability_passed": True,
        "research_evidence_passed": True,
        "in_sample_direction_correct": in_sample_direction_correct,
        "oos_direction_not_reversed": oos_direction_not_reversed,
        "in_sample_q5_q1_spread_positive": in_sample_q5_q1_positive,
        "oos_q5_q1_spread_not_reversed": oos_q5_q1_not_reversed,
        "top_quantile_return_positive": top_quantile_return_positive,
        "stronger_than_most_noise_baselines": bool(stronger_than_noise),
        "not_worse_than_simple_technical_baselines": not_worse_than_simple is not False,
        "no_single_year_concentration": single_year_flag is not True,
        "turnover_and_drawdown_not_uncontrolled": turnover_and_drawdown_ok,
    }

    if not oos_direction_not_reversed:
        reasons.append("OOS RankIC is reversed")
    if not oos_q5_q1_not_reversed:
        reasons.append("OOS Q5-Q1 spread is reversed")
    if stronger_than_noise is False:
        reasons.append("candidate does not beat most noise baselines")
    if turnover_and_drawdown_ok is False:
        reasons.append("turnover or drawdown looks uncontrolled")

    if all(active_requirements.values()):
        status = "active"
        reasons = reasons or ["meets conservative active policy"]
    elif (not in_sample_direction_correct) and (not oos_direction_not_reversed):
        status = "rejected"
        reasons = reasons or ["in-sample and OOS both fail direction check"]
    elif stronger_than_noise is False and not oos_direction_not_reversed:
        status = "rejected"
        reasons = reasons or ["OOS fails and baseline comparison is weak"]
    else:
        status = library_cfg.get("default_pass_status", "watch")
        reasons = reasons or ["passes research gate but active evidence is not yet enough"]

    return {
        "passed": status in {"watch", "active"},
        "status": status,
        "reasons": reasons,
        "evidence": active_requirements,
    }
