"""AgentCore Platform v1.0"""

# Inner domain workflow node (docs/02_design.md — proposal step 3:
# GapClassify). Deterministic three-tier severity classification from
# ThresholdCheckNode's output — NO LLM (see compliance_gap_service.py
# module docstring for the Design Decision Record rationale).

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.compliance_gap_service import classify_severity


class GapClassifyNode(FunctionNode):
    """Assign a severity tier (critical/significant/advisory/compliant/unconfigured) to each record."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        critical_gap_threshold_pct: float = 15.0,
        significant_gap_threshold_pct: float = 5.0,
    ) -> None:
        super().__init__()
        self._critical_gap_threshold_pct = critical_gap_threshold_pct
        self._significant_gap_threshold_pct = significant_gap_threshold_pct

    def execute(self, state: AgentState) -> dict[str, Any]:
        threshold_results = state.get("threshold_results", [])

        gap_classifications = [
            classify_severity(r, self._critical_gap_threshold_pct, self._significant_gap_threshold_pct)
            for r in threshold_results
        ]

        severity_counts: dict[str, int] = {}
        for item in gap_classifications:
            severity_counts[item["severity"]] = severity_counts.get(item["severity"], 0) + 1

        emit_trace_event("gaps_classified", {"severity_counts": severity_counts}, state)

        return {
            "gap_classifications": gap_classifications,
            "status": AgentStatus.SUCCESS.value,
        }
