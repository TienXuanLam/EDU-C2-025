# EDU-C2-025 — Unit Tests: compliance_gap_service (BL-05..BL-14)

from src.services.compliance_gap_service import check_threshold, classify_severity, score_and_rank

THRESHOLDS = {"harassment_prevention": 90.0, "occupational_safety": 95.0}


class TestCheckThreshold:
    def test_below_threshold_computes_gap(self):
        """BL-05: a record below threshold gets a positive gap_pct."""
        record = {"training_domain": "harassment_prevention", "completion_rate": 82.5}
        result = check_threshold(record, THRESHOLDS)
        assert result["below_threshold"] is True
        assert result["gap_pct"] == 7.5
        assert result["threshold"] == 90.0

    def test_at_or_above_threshold_is_compliant(self):
        """BL-06: completion_rate == threshold is NOT below (strict less-than)."""
        record = {"training_domain": "harassment_prevention", "completion_rate": 90.0}
        result = check_threshold(record, THRESHOLDS)
        assert result["below_threshold"] is False
        assert result["gap_pct"] == 0.0

    def test_unconfigured_domain_returns_none(self):
        """BL-07: a domain with no configured threshold is None, not False."""
        record = {"training_domain": "unknown_domain", "completion_rate": 10.0}
        result = check_threshold(record, THRESHOLDS)
        assert result["below_threshold"] is None
        assert result["threshold"] is None
        assert result["gap_pct"] is None


class TestClassifySeverity:
    def test_unconfigured_domain_severity(self):
        """BL-08: below_threshold=None -> unconfigured_domain, not compliant/critical."""
        threshold_result = {"below_threshold": None, "gap_pct": None}
        result = classify_severity(threshold_result, critical_gap_threshold_pct=15.0, significant_gap_threshold_pct=5.0)
        assert result["severity"] == "unconfigured_domain"

    def test_compliant_severity(self):
        threshold_result = {"below_threshold": False, "gap_pct": 0.0}
        result = classify_severity(threshold_result, critical_gap_threshold_pct=15.0, significant_gap_threshold_pct=5.0)
        assert result["severity"] == "compliant"

    def test_critical_band(self):
        """BL-09: gap_pct at or above critical_gap_threshold_pct is critical."""
        threshold_result = {"below_threshold": True, "gap_pct": 20.0}
        result = classify_severity(threshold_result, critical_gap_threshold_pct=15.0, significant_gap_threshold_pct=5.0)
        assert result["severity"] == "critical"

    def test_significant_band(self):
        threshold_result = {"below_threshold": True, "gap_pct": 10.0}
        result = classify_severity(threshold_result, critical_gap_threshold_pct=15.0, significant_gap_threshold_pct=5.0)
        assert result["severity"] == "significant"

    def test_advisory_band(self):
        threshold_result = {"below_threshold": True, "gap_pct": 2.0}
        result = classify_severity(threshold_result, critical_gap_threshold_pct=15.0, significant_gap_threshold_pct=5.0)
        assert result["severity"] == "advisory"

    def test_band_boundary_is_inclusive(self):
        """BL-10: gap_pct exactly at a band cutoff belongs to the higher-severity band."""
        threshold_result = {"below_threshold": True, "gap_pct": 15.0}
        result = classify_severity(threshold_result, critical_gap_threshold_pct=15.0, significant_gap_threshold_pct=5.0)
        assert result["severity"] == "critical"

        threshold_result = {"below_threshold": True, "gap_pct": 5.0}
        result = classify_severity(threshold_result, critical_gap_threshold_pct=15.0, significant_gap_threshold_pct=5.0)
        assert result["severity"] == "significant"


class TestScoreAndRank:
    def test_ranks_gap_items_by_descending_score(self):
        """BL-11: higher risk_weight * gap_pct ranks first."""
        items = [
            {"training_domain": "occupational_safety", "severity": "critical", "gap_pct": 10.0},
            {"training_domain": "harassment_prevention", "severity": "significant", "gap_pct": 20.0},
        ]
        weights = {"occupational_safety": 5.0, "harassment_prevention": 4.0}
        result = score_and_rank(items, weights, default_risk_weight=3.0)
        # occupational_safety: 5*10=50, harassment_prevention: 4*20=80 -> harassment first
        assert result[0]["training_domain"] == "harassment_prevention"
        assert result[0]["rank"] == 1
        assert result[1]["rank"] == 2

    def test_non_gap_items_get_zero_score_and_no_rank(self):
        """BL-12: compliant/unconfigured items are unranked and sorted after gap items."""
        items = [
            {"training_domain": "harassment_prevention", "severity": "compliant", "gap_pct": 0.0},
            {"training_domain": "occupational_safety", "severity": "critical", "gap_pct": 10.0},
        ]
        weights = {"occupational_safety": 5.0}
        result = score_and_rank(items, weights, default_risk_weight=3.0)
        assert result[0]["severity"] == "critical"
        assert result[0]["rank"] == 1
        assert result[1]["severity"] == "compliant"
        assert result[1]["rank"] is None
        assert result[1]["risk_score"] == 0.0

    def test_default_risk_weight_used_when_domain_missing(self):
        """BL-13: a gap item whose domain has no configured risk_weight uses the default."""
        items = [{"training_domain": "whistleblower_protection", "severity": "advisory", "gap_pct": 4.0}]
        result = score_and_rank(items, risk_weights={}, default_risk_weight=3.0)
        assert result[0]["risk_score"] == 12.0  # 3.0 * 4.0

    def test_empty_input_returns_empty_list(self):
        """BL-14: no gap items -> empty ranked list, no crash."""
        assert score_and_rank([], {}, default_risk_weight=3.0) == []
