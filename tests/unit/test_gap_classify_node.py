# EDU-C2-025 — Unit Tests: GapClassifyNode (BL-31..BL-32)

from src.nodes.gap_classify_node import GapClassifyNode


class TestGapClassifyNode:
    def test_classifies_each_threshold_result(self):
        """BL-31: each threshold_result gets a severity tier."""
        node = GapClassifyNode(critical_gap_threshold_pct=15.0, significant_gap_threshold_pct=5.0)
        state = {
            "threshold_results": [
                {"training_domain": "harassment_prevention", "below_threshold": True, "gap_pct": 20.0},
                {"training_domain": "occupational_safety", "below_threshold": False, "gap_pct": 0.0},
                {"training_domain": "unknown", "below_threshold": None, "gap_pct": None},
            ],
            "node_history": [],
            "error_log": [],
        }
        result = node.execute(state)
        assert result["status"] == "success"
        severities = [c["severity"] for c in result["gap_classifications"]]
        assert severities == ["critical", "compliant", "unconfigured_domain"]

    def test_empty_threshold_results_does_not_crash(self):
        """BL-32: no records -> empty classifications, no crash."""
        node = GapClassifyNode()
        result = node.execute({"threshold_results": [], "node_history": [], "error_log": []})
        assert result["status"] == "success"
        assert result["gap_classifications"] == []
