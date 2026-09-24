# EDU-C2-025 — Unit Tests: CompletionDataIngestNode (BL-15..BL-27)

import json

from framework.schemas.trust_level import TrustLevel
from src.nodes.completion_data_ingest_node import CompletionDataIngestNode


def _state(user_input: str) -> dict:
    return {
        "user_input": user_input,
        "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
        "correlation_id": "test-corr",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "",
        "caller_id": "",
        "hitl_allowed": True,
        "node_history": [],
        "error_log": [],
    }


VALID_PAYLOAD = json.dumps(
    {
        "reporting_period": "FY2026-Q2",
        "records": [
            {
                "training_domain": "harassment_prevention",
                "business_unit": "Sales",
                "role_category": "manager",
                "completion_rate": 82.5,
            }
        ],
    }
)


class TestCompletionDataIngestNode:
    def setup_method(self):
        self.node = CompletionDataIngestNode()

    def test_success_path(self):
        """BL-15: valid JSON input is parsed and normalized."""
        result = self.node.execute(_state(VALID_PAYLOAD))
        assert result["status"] == "success"
        assert result["reporting_period"] == "FY2026-Q2"
        assert result["mode"] == "full_report"
        assert result["records"][0]["completion_rate"] == 82.5
        assert json.loads(result["validated_input"])["reporting_period"] == "FY2026-Q2"

    def test_malformed_json(self):
        """BL-16: non-JSON input is rejected."""
        result = self.node.execute(_state("not json at all"))
        assert result["status"] == "error"
        assert result["error_log"]

    def test_valid_json_non_object_is_rejected(self):
        result = self.node.execute(_state("[]"))
        assert result["status"] == "error"

    def test_missing_reporting_period(self):
        """BL-17: missing required field is rejected."""
        payload = json.dumps({"records": [{"training_domain": "x", "business_unit": "y", "role_category": "z", "completion_rate": 50}]})
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_empty_records_rejected(self):
        """BL-18: records must contain at least one entry."""
        payload = json.dumps({"reporting_period": "FY2026-Q2", "records": []})
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_records_not_a_list_rejected(self):
        """BL-19: records must be a list, not e.g. a dict."""
        payload = json.dumps({"reporting_period": "FY2026-Q2", "records": {"a": 1}})
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_missing_record_field_rejected(self):
        payload = json.dumps(
            {"reporting_period": "FY2026-Q2", "records": [{"training_domain": "x", "business_unit": "y"}]}
        )
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_completion_rate_out_of_range_rejected(self):
        """BL-20: completion_rate must be within [0, 100]."""
        payload = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "records": [
                    {"training_domain": "x", "business_unit": "y", "role_category": "z", "completion_rate": 150}
                ],
            }
        )
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_completion_rate_boolean_rejected(self):
        """bool is an int subclass in Python — must not silently coerce."""
        payload = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "records": [
                    {"training_domain": "x", "business_unit": "y", "role_category": "z", "completion_rate": True}
                ],
            }
        )
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_completion_rate_non_numeric_rejected(self):
        payload = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "records": [
                    {"training_domain": "x", "business_unit": "y", "role_category": "z", "completion_rate": "high"}
                ],
            }
        )
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_non_finite_completion_rates_rejected(self):
        for rate in (float("nan"), float("inf"), float("-inf")):
            payload = json.dumps(
                {
                    "reporting_period": "FY2026-Q2",
                    "records": [
                        {
                            "training_domain": "x",
                            "business_unit": "y",
                            "role_category": "z",
                            "completion_rate": rate,
                        }
                    ],
                }
            )
            assert self.node.execute(_state(payload))["status"] == "error"

    def test_control_character_in_label_is_rejected(self):
        payload = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "records": [
                    {
                        "training_domain": "harassment_prevention\n## injected",
                        "business_unit": "Sales",
                        "role_category": "manager",
                        "completion_rate": 80,
                    }
                ],
            }
        )
        assert self.node.execute(_state(payload))["status"] == "error"

    def test_boundary_completion_rate_values_accepted(self):
        """0 and 100 are the inclusive bounds — must not be rejected."""
        for rate in (0, 100):
            payload = json.dumps(
                {
                    "reporting_period": "FY2026-Q2",
                    "records": [
                        {"training_domain": "x", "business_unit": "y", "role_category": "z", "completion_rate": rate}
                    ],
                }
            )
            result = self.node.execute(_state(payload))
            assert result["status"] == "success", f"completion_rate={rate} should be accepted"

    def test_invalid_mode_rejected(self):
        payload = json.dumps({"reporting_period": "FY2026-Q2", "mode": "bogus_mode", "records": [{"training_domain": "x", "business_unit": "y", "role_category": "z", "completion_rate": 50}]})
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_deterministic_only_mode_accepted(self):
        payload = json.dumps(
            {
                "reporting_period": "FY2026-Q2",
                "mode": "deterministic_only",
                "records": [
                    {"training_domain": "x", "business_unit": "y", "role_category": "z", "completion_rate": 50}
                ],
            }
        )
        result = self.node.execute(_state(payload))
        assert result["status"] == "success"
        assert result["mode"] == "deterministic_only"

    def test_records_exceeds_max_count_rejected(self):
        records = [
            {"training_domain": "x", "business_unit": "y", "role_category": "z", "completion_rate": 50}
            for _ in range(501)
        ]
        payload = json.dumps({"reporting_period": "FY2026-Q2", "records": records})
        result = self.node.execute(_state(payload))
        assert result["status"] == "error"

    def test_s2_rejects_individual_identifier_via_call(self):
        """__call__() runs the S-2 hook and rejects a per-employee row."""
        payload = json.dumps(
            {"reporting_period": "FY2026-Q2", "records": [{"employee_name": "Taro Yamada", "completion_rate": 100}]}
        )
        result = self.node(_state(payload))  # via __call__ — S-2 hook runs here
        assert result["status"] == "error"

    def test_s2_allows_clean_aggregated_payload(self):
        result = self.node(_state(VALID_PAYLOAD))
        assert result["status"] == "success"
