# EDU-C2-025 — Unit Tests: ReportDraftNode (BL-35..BL-38)

from src.nodes.report_draft_node import ReportDraftNode


class FakeLLM:
    """Matches shared.services.llm.base_llm.BaseLLM.complete() — takes a
    message list, returns the canonical {"content": ..., "tool_calls": [],
    "model": ...} dict."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, messages: list) -> dict:
        return {"content": self._response, "tool_calls": [], "model": "fake"}


class RaisingLLM:
    """Simulates a provider/network exception during complete()."""

    def complete(self, messages: list) -> dict:
        raise ConnectionError("simulated provider outage")


def _state() -> dict:
    return {
        "reporting_period": "FY2026-Q2",
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
    }


def _node_with_llm(llm) -> ReportDraftNode:
    """ReportDraftNode builds its own LLM per invocation via _build_llm(state)
    rather than accepting a constructor-injected client — inject the test
    double by patching the bound method on this instance instead."""
    node = ReportDraftNode()
    node._build_llm = lambda state: llm
    return node


class TestReportDraftNode:
    def test_success_path(self):
        """BL-35: LLM supplies narrative; computed sections stay deterministic."""
        node = _node_with_llm(FakeLLM("## Executive Summary\n..."))
        result = node.execute(_state())
        assert result["status"] == "success"
        assert "Executive Summary" in result["gap_report_markdown"]
        assert "Per-Unit Completion Table" in result["gap_report_markdown"]
        assert "82.5%" in result["gap_report_markdown"]
        assert "risk_score 30.0" in result["gap_report_markdown"]

    def test_missing_llm_secret_fails_closed(self):
        """BL-36 (updated): a missing Azure OpenAI secret (or any _build_llm
        failure) must return status=error via the existing except-Exception
        path in execute(), not crash (PB-6 safety)."""
        node = ReportDraftNode()

        def _raise(state):
            raise RuntimeError("simulated missing secret")

        node._build_llm = _raise
        result = node.execute(_state())
        assert result["status"] == "error"

    def test_llm_provider_exception_fails_closed(self):
        """BL-37: a provider/network exception must return status=error, not
        propagate an unhandled exception out of execute()."""
        node = _node_with_llm(RaisingLLM())
        result = node.execute(_state())
        assert result["status"] == "error"
        assert result["error_log"]

    def test_llm_empty_content_is_an_error(self):
        """BL-38: empty LLM content must not be silently treated as success."""
        node = _node_with_llm(FakeLLM(""))
        result = node.execute(_state())
        assert result["status"] == "error"

    def test_numeric_or_section_injection_from_llm_is_rejected(self):
        for response in (
            "Completion is 100 percent.",
            "## Priority Actions\nInvented action",
        ):
            result = _node_with_llm(FakeLLM(response)).execute(_state())
            assert result["status"] == "error"

    def test_narrating_supplied_numbers_back_is_not_rejected(self):
        """A real LLM narrates supplied facts back (e.g. "completion stood
        at 82.5% against a 90.0% threshold, risk score 30") rather than
        reproducing them verbatim — that is not fabrication. Regression
        guard for a bug where a blanket "any digit -> error" check rejected
        every real LLM response and only ever passed a FakeLLM whose fixed
        text happened to contain no digits at all."""
        response = (
            "Completion stood at 82.5% against a 90.0% threshold, a gap of 7.5 points "
            "with a risk score of 30. No items were flagged for escalation."
        )
        result = _node_with_llm(FakeLLM(response)).execute(_state())
        assert result["status"] == "success"
