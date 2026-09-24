"""Fail-closed validation for compliance policy configuration."""

import pytest
from framework.errors import ConfigError

from src.graph.graph import ComplianceTrainingCompletionTrackingGapReportAgent


def _config(**overrides):
    config = {
        "thresholds": {"harassment_prevention": 90.0},
        "risk_weights": {"harassment_prevention": 4.0},
        "critical_gap_threshold_pct": 15.0,
        "significant_gap_threshold_pct": 5.0,
    }
    config.update(overrides)
    return config


@pytest.mark.parametrize(
    "override",
    (
        {"thresholds": {}},
        {"thresholds": {"harassment_prevention": float("nan")}},
        {"risk_weights": {"harassment_prevention": -1.0}},
        {"critical_gap_threshold_pct": 5.0, "significant_gap_threshold_pct": 15.0},
    ),
)
def test_invalid_policy_config_blocks_compile(override):
    agent = ComplianceTrainingCompletionTrackingGapReportAgent(config=_config(**override))
    with pytest.raises(ConfigError):
        agent.compile()
