# EDU-C2-025 — Unit Tests: ThresholdCheckNode (BL-28..BL-30)

import json

from src.nodes.threshold_check_node import ThresholdCheckNode

THRESHOLDS = {"harassment_prevention": 90.0}


def _state(payload: dict) -> dict:
    return {"user_input": json.dumps(payload), "node_history": [], "error_log": []}


class TestThresholdCheckNode:
    def test_rehydrates_and_computes_gap(self):
        """BL-28: forwarded JSON is re-parsed and each record checked against threshold."""
        node = ThresholdCheckNode(THRESHOLDS)
        payload = {
            "mode": "full_report",
            "reporting_period": "FY2026-Q2",
            "records": [
                {"training_domain": "harassment_prevention", "business_unit": "Sales", "role_category": "manager", "completion_rate": 82.5}
            ],
        }
        result = node.execute(_state(payload))
        assert result["status"] == "success"
        assert result["reporting_period"] == "FY2026-Q2"
        assert result["threshold_results"][0]["below_threshold"] is True
        assert result["threshold_results"][0]["gap_pct"] == 7.5

    def test_unconfigured_domain_not_below_threshold_false(self):
        """BL-29: an unconfigured domain is None, not incorrectly marked compliant."""
        node = ThresholdCheckNode(THRESHOLDS)
        payload = {
            "mode": "full_report",
            "reporting_period": "FY2026-Q2",
            "records": [
                {"training_domain": "unknown_domain", "business_unit": "Sales", "role_category": "manager", "completion_rate": 10.0}
            ],
        }
        result = node.execute(_state(payload))
        assert result["threshold_results"][0]["below_threshold"] is None

    def test_no_thresholds_configured_does_not_crash(self):
        """BL-30: an empty thresholds dict (default) does not crash — every record is unconfigured."""
        node = ThresholdCheckNode()
        payload = {"mode": "full_report", "reporting_period": "FY2026-Q2", "records": []}
        result = node.execute(_state(payload))
        assert result["status"] == "success"
        assert result["threshold_results"] == []
