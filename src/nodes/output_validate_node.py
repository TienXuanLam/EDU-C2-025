"""AgentCore Platform v1.0"""

# Outer post_process node (docs/02_design.md — proposal step 6:
# OutputValidate). Attaches the mandatory disclaimer (risk #1 mitigation —
# proposal §11) and re-scans the generated report text for apparent
# individual-level data before output leaves the node boundary — the LLM
# output is not proposal-guaranteed clean, even though the upstream data is
# aggregated only.
#
# deterministic_only mode (docs/02_design.md): ReportDraftNode (LLM) never
# ran, so gap_report_markdown is empty — this node renders priority_ranked
# directly into the same report shape instead of leaving a blank report.

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.individual_identifier_scan import contains_individual_identifier_text
from src.services.report_render_service import render_report

DISCLAIMER = (
    "\n\n---\n**⚠️ AI draft — HR/Compliance must verify source data accuracy and "
    "business unit labels before distribution to management or the audit "
    "committee.**"
)


class OutputValidateNode(FunctionNode):
    """Finalize the gap report and attach the mandatory disclaimer."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        if contains_individual_identifier_text(str(result.get("final_report_markdown", ""))):
            raise RuntimeError(
                "OutputValidateNode: S-3 rejected output — apparent individual-level "
                "identifier detected in generated report"
            )
        return result

    def execute(self, state: AgentState) -> dict[str, Any]:
        if state.get("status") == AgentStatus.ERROR.value:
            return {"status": AgentStatus.ERROR.value}

        mode = state.get("mode", "full_report")
        body = (
            state.get("gap_report_markdown", "")
            if mode == "full_report"
            else render_report(
                str(state.get("reporting_period", "")),
                state.get("priority_ranked", []),
            )
        )
        markdown = body + DISCLAIMER

        emit_trace_event(
            "gap_report_finalized", {"reporting_period": state.get("reporting_period", ""), "mode": mode}, state
        )

        return {
            "final_report_markdown": markdown,
            "formatted_output": markdown,
            "status": AgentStatus.SUCCESS.value,
        }
