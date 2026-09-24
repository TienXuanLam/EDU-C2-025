# EDU-C2-025 — Unit Tests: RiskPriorityScoreNode (BL-33..BL-34)

from src.nodes.risk_priority_score_node import RiskPriorityScoreNode


class TestRiskPriorityScoreNode:
    def test_scores_and_ranks_gap_items(self):
        """BL-33: gap items are scored and ranked; non-gap items are not."""
        node = RiskPriorityScoreNode(risk_weights={"harassment_prevention": 4.0}, default_risk_weight=3.0)
        state = {
            "gap_classifications": [
                {"training_domain": "harassment_prevention", "severity": "critical", "gap_pct": 20.0},
                {"training_domain": "occupational_safety", "severity": "compliant", "gap_pct": 0.0},
            ],
            "node_history": [],
            "error_log": [],
        }
        result = node.execute(state)
        assert result["status"] == "success"
        assert result["priority_ranked"][0]["rank"] == 1
        assert result["priority_ranked"][0]["risk_score"] == 80.0
        assert result["priority_ranked"][1]["rank"] is None

    def test_empty_gap_classifications_does_not_crash(self):
        """BL-34: no classifications -> empty ranked list, no crash."""
        node = RiskPriorityScoreNode()
        result = node.execute({"gap_classifications": [], "node_history": [], "error_log": []})
        assert result["status"] == "success"
        assert result["priority_ranked"] == []
