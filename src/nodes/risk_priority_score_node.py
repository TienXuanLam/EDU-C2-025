"""AgentCore Platform v1.0"""

# Inner domain workflow node (docs/02_design.md — proposal step 4:
# RiskPriorityScore). Deterministic regulatory-risk-weighted scoring and
# ranking — NO LLM (see compliance_gap_service.py module docstring).

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.compliance_gap_service import score_and_rank


class RiskPriorityScoreNode(FunctionNode):
    """Score gap items by regulatory risk weight x gap magnitude and rank them."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        risk_weights: dict[str, float] | None = None,
        default_risk_weight: float = 3.0,
    ) -> None:
        super().__init__()
        self._risk_weights = risk_weights or {}
        self._default_risk_weight = default_risk_weight

    def execute(self, state: AgentState) -> dict[str, Any]:
        gap_classifications = state.get("gap_classifications", [])

        priority_ranked = score_and_rank(gap_classifications, self._risk_weights, self._default_risk_weight)
        ranked_count = sum(1 for i in priority_ranked if i.get("rank") is not None)

        emit_trace_event("gaps_scored_and_ranked", {"ranked_count": ranked_count}, state)

        return {
            "priority_ranked": priority_ranked,
            "status": AgentStatus.SUCCESS.value,
        }
