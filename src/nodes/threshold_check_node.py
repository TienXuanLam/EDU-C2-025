"""AgentCore Platform v1.0"""

# Inner domain workflow node (docs/02_design.md — proposal step 2:
# ThresholdCheck). First node of the inner graph: BaseGraph.invoke() only
# forwards a single string (the outer node's extract_input() return value, a
# JSON string built by CompletionDataIngestNode) — this node re-parses it and
# rehydrates the individual fields into inner state for downstream nodes.

from __future__ import annotations

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.compliance_gap_service import check_threshold


class ThresholdCheckNode(FunctionNode):
    """Parse the forwarded request and compare each record against its threshold."""

    # S-1: matches config/agent.yaml's agent-level required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        super().__init__()
        self._thresholds = thresholds or {}

    def execute(self, state: AgentState) -> dict[str, Any]:
        raw = state.get("user_input", "") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        mode = payload.get("mode", "full_report")
        reporting_period = payload.get("reporting_period", "")
        records = payload.get("records", []) or []

        threshold_results = [check_threshold(record, self._thresholds) for record in records]
        unconfigured_count = sum(1 for r in threshold_results if r["below_threshold"] is None)

        emit_trace_event(
            "thresholds_checked",
            {"record_count": len(threshold_results), "unconfigured_domain_count": unconfigured_count},
            state,
        )

        return {
            "mode": mode,
            "reporting_period": reporting_period,
            "records": records,
            "threshold_results": threshold_results,
            "status": AgentStatus.SUCCESS.value,
        }
