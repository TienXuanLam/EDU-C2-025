"""AgentCore Platform v1.0"""

# Pure domain logic for the three deterministic inner-graph steps
# (ThresholdCheckNode, GapClassifyNode, RiskPriorityScoreNode — proposal §4).
# No LLM, no agenticstar/framework imports — testable in isolation, the same
# pattern used elsewhere in the fleet for pure domain-logic services.
#
# Per the same Design Decision Record principle used elsewhere in the
# fleet: which units are below threshold, how severe the gap is,
# and how gaps are ranked are all regulatory-risk-material judgments — they
# must never be LLM-arbitrated. ReportDraftNode (LLM) only turns this
# already-computed structured data into prose; it does not decide it.

from __future__ import annotations

import math
from typing import Any

_UNCONFIGURED = "unconfigured_domain"
_COMPLIANT = "compliant"
_CRITICAL = "critical"
_SIGNIFICANT = "significant"
_ADVISORY = "advisory"


def validate_gap_config(config: dict[str, Any]) -> None:
    """Reject missing or nonsensical policy values before graph construction."""
    thresholds = config.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("'thresholds' must be a non-empty mapping")
    for domain, value in thresholds.items():
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError("threshold domain keys must be non-empty strings")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"threshold for {domain!r} must be numeric")
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 100.0:
            raise ValueError(f"threshold for {domain!r} must be finite and between 0 and 100")

    risk_weights = config.get("risk_weights") or {}
    if not isinstance(risk_weights, dict):
        raise ValueError("'risk_weights' must be a mapping")
    for domain, value in risk_weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"risk weight for {domain!r} must be numeric")
        if not math.isfinite(float(value)) or float(value) <= 0.0:
            raise ValueError(f"risk weight for {domain!r} must be finite and greater than zero")

    default_weight = config.get("default_risk_weight", 3.0)
    if isinstance(default_weight, bool) or not isinstance(default_weight, (int, float)):
        raise ValueError("'default_risk_weight' must be numeric")
    if not math.isfinite(float(default_weight)) or float(default_weight) <= 0.0:
        raise ValueError("'default_risk_weight' must be finite and greater than zero")

    critical = config.get("critical_gap_threshold_pct", 15.0)
    significant = config.get("significant_gap_threshold_pct", 5.0)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in (critical, significant)):
        raise ValueError("severity gap thresholds must be numeric")
    if not all(math.isfinite(float(value)) for value in (critical, significant)):
        raise ValueError("severity gap thresholds must be finite")
    if not 0.0 < float(significant) < float(critical) <= 100.0:
        raise ValueError("severity thresholds must satisfy 0 < significant < critical <= 100")

    system_prompt = config.get("system_prompt")
    if system_prompt is not None and not isinstance(system_prompt, str):
        raise ValueError("'system_prompt' must be a string or null")


def check_threshold(record: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    """Compare one record's completion_rate against its configured threshold.

    Returns record enriched with: threshold (float|None), gap_pct (float|None,
    only set when below threshold), below_threshold (bool|None — None means
    the training_domain has no configured threshold, not "compliant").
    """
    domain = record.get("training_domain", "")
    completion_rate = record.get("completion_rate", 0.0)
    threshold = thresholds.get(domain)

    if threshold is None:
        return {**record, "threshold": None, "gap_pct": None, "below_threshold": None}

    below = completion_rate < threshold
    gap_pct = round(threshold - completion_rate, 2) if below else 0.0
    return {**record, "threshold": threshold, "gap_pct": gap_pct, "below_threshold": below}


def classify_severity(
    threshold_result: dict[str, Any],
    critical_gap_threshold_pct: float,
    significant_gap_threshold_pct: float,
) -> dict[str, Any]:
    """Assign a severity tier from an already-computed threshold_result.

    Tiers: "unconfigured_domain" (no threshold to compare against),
    "compliant" (not below threshold), "critical" / "significant" / "advisory"
    (below threshold, by descending gap_pct band).
    """
    below = threshold_result.get("below_threshold")
    if below is None:
        severity = _UNCONFIGURED
    elif not below:
        severity = _COMPLIANT
    else:
        gap_pct = threshold_result.get("gap_pct", 0.0)
        if gap_pct >= critical_gap_threshold_pct:
            severity = _CRITICAL
        elif gap_pct >= significant_gap_threshold_pct:
            severity = _SIGNIFICANT
        else:
            severity = _ADVISORY

    return {**threshold_result, "severity": severity}


def score_and_rank(
    gap_classifications: list[dict[str, Any]],
    risk_weights: dict[str, float],
    default_risk_weight: float,
) -> list[dict[str, Any]]:
    """Compute regulatory-risk score (risk_weight * gap_pct) and rank gap items.

    Only "critical" / "significant" / "advisory" items receive a rank
    (1 = highest risk_score); "compliant" and "unconfigured_domain" items get
    score=0.0, rank=None and are sorted after all ranked items, preserving
    their relative input order (stable sort).
    """
    gap_severities = {_CRITICAL, _SIGNIFICANT, _ADVISORY}

    scored: list[dict[str, Any]] = []
    for item in gap_classifications:
        if item.get("severity") in gap_severities:
            domain = item.get("training_domain", "")
            weight = risk_weights.get(domain, default_risk_weight)
            score = round(weight * item.get("gap_pct", 0.0), 2)
        else:
            score = 0.0
        scored.append({**item, "risk_score": score})

    ranked_items = [i for i in scored if i.get("severity") in gap_severities]
    other_items = [i for i in scored if i.get("severity") not in gap_severities]
    ranked_items.sort(key=lambda i: i["risk_score"], reverse=True)

    result: list[dict[str, Any]] = []
    for rank, item in enumerate(ranked_items, start=1):
        result.append({**item, "rank": rank})
    for item in other_items:
        result.append({**item, "rank": None})
    return result
