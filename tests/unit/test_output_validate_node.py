# EDU-C2-025 — Unit Tests: OutputValidateNode (BL-39..BL-45)

from framework.schemas.trust_level import TrustLevel
from src.nodes.output_validate_node import DISCLAIMER, OutputValidateNode


def _state(**overrides) -> dict:
    state = {
        "mode": "full_report",
        "reporting_period": "FY2026-Q2",
        "gap_report_markdown": "## Executive Summary\nHarassment prevention is at 82.5% for Sales.",
        "priority_ranked": [
            {
                "training_domain": "harassment_prevention",
                "business_unit": "Sales",
                "role_category": "manager",
                "completion_rate": 82.5,
                "threshold": 90.0,
                "gap_pct": 7.5,
                "severity": "significant",
                "risk_score": 30.0,
                "rank": 1,
            }
        ],
        "node_history": [],
        "error_log": [],
        "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
        "correlation_id": "test-corr",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "",
        "caller_id": "",
        "hitl_allowed": True,
    }
    state.update(overrides)
    return state


class TestOutputValidateNode:
    def setup_method(self):
        self.node = OutputValidateNode()

    def test_disclaimer_always_present(self):
        """BL-39: the mandatory disclaimer is always attached."""
        result = self.node.execute(_state())
        assert result["status"] == "success"
        assert result["formatted_output"].endswith(DISCLAIMER.strip("\n"))

    def test_full_report_mode_uses_llm_markdown(self):
        """BL-40: full_report mode passes gap_report_markdown through as-is."""
        result = self.node.execute(_state())
        assert "Executive Summary" in result["formatted_output"]

    def test_deterministic_only_mode_renders_table_without_llm(self):
        """BL-41: deterministic_only mode renders priority_ranked directly — no LLM content needed."""
        result = self.node.execute(_state(mode="deterministic_only", gap_report_markdown=""))
        assert result["status"] == "success"
        assert "Per-Unit Completion Table" in result["formatted_output"]
        assert "harassment_prevention" in result["formatted_output"]

    def test_deterministic_only_escalates_critical_items(self):
        """BL-42: a critical-severity item appears under Escalation Flags."""
        state = _state(
            mode="deterministic_only",
            gap_report_markdown="",
            priority_ranked=[
                {
                    "training_domain": "occupational_safety",
                    "business_unit": "Manufacturing",
                    "role_category": "staff",
                    "completion_rate": 60.0,
                    "threshold": 95.0,
                    "gap_pct": 35.0,
                    "severity": "critical",
                    "risk_score": 175.0,
                    "rank": 1,
                }
            ],
        )
        result = self.node.execute(state)
        escalation_section = result["formatted_output"].split("## Escalation Flags")[1]
        assert "occupational_safety" in escalation_section

    def test_s3_rejects_unsafe_output(self):
        """BL-43: invoked via __call__() — the real S-1->S-2->execute->S-3
        lifecycle, not execute() + the hook called directly (which bypasses
        _security_gate_output(), the @final method that actually decides
        whether the RuntimeError is caught and turned into status=error).
        Also proves no formatted_output leaks into the blocked result."""
        state = _state(gap_report_markdown="Employee ID 00231 has not completed the training.")
        result = self.node(state)  # __call__ — full S-1..S-4 lifecycle
        assert result["status"] == "error"
        assert "formatted_output" not in result
        assert "final_report_markdown" not in result

    def test_trust_gate_rejects_anonymous_caller(self):
        """BL-44/TC-08: OutputValidateNode requires VERIFIED_EXTERNAL — must call
        via __call__() (not execute()) since the S-1 gate lives in __call__()."""
        state = _state(caller_trust_level=TrustLevel.ANONYMOUS.value)
        result = self.node(state)
        assert result["status"] == "error"

    def test_trust_gate_allows_verified_external_caller(self):
        """BL-45"""
        state = _state(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL.value)
        result = self.node(state)
        assert result["status"] == "success"
