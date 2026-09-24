"""AgentCore Platform v1.0"""

from __future__ import annotations

# EDU-C2-025 — Cat 2: AgentBaseGraph (outer, fixed 5-node backbone) + GraphNode
# in the `main` slot wrapping the inner domain workflow graph
# (src/graph/domain_workflow_graph.py). Proposal §4 lists 6 steps
# (CompletionDataIngest / ThresholdCheck / GapClassify / RiskPriorityScore /
# ReportDraft / OutputValidate) — more than AgentBaseGraph's 3 fixed slots, so
# the 4 middle steps are encapsulated in the inner graph, matching the current
# Cat 2 scaffold convention (src/examples/graph_cat2_sample.py).
#
# Do NOT override add_edges() on this outer graph — backbone wiring
# (initialize -> pre_process -> main -> {route} -> post_process -> finalize)
# belongs to AgentBaseGraph.

from typing import TYPE_CHECKING, Any, ClassVar

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.errors import ConfigError
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from src.nodes.completion_data_ingest_node import CompletionDataIngestNode
from src.nodes.output_validate_node import OutputValidateNode
from src.schemas.state import State
from src.services.compliance_gap_service import validate_gap_config

if TYPE_CHECKING:
    from src.graph.domain_workflow_graph import ComplianceGapWorkflowGraph


class ComplianceGapWorkflowGraphNode(GraphNode):
    """Wraps the inner domain workflow graph; assigned to the outer `main` slot."""

    # S-1: check_trust_level.py only scans direct FunctionNode subclasses, so
    # GraphNode subclasses default to ANONYMOUS silently unless declared here
    # explicitly. Matches config/agent.yaml's agent-level required_trust_level
    # and the other two outer nodes.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    error_strategy: ClassVar[str] = "propagate"  # fail fast — no silent partial gap report
    propagate_hitl: ClassVar[bool] = False

    def __init__(
        self,
        llm_config: dict[str, Any] | None = None,
        timeout_s: int = 120,
        thresholds: dict[str, float] | None = None,
        risk_weights: dict[str, float] | None = None,
        default_risk_weight: float = 3.0,
        critical_gap_threshold_pct: float = 15.0,
        significant_gap_threshold_pct: float = 5.0,
        system_prompt: str | None = None,
    ) -> None:
        super().__init__()
        self._llm_config = llm_config
        self._timeout_s = timeout_s
        self._thresholds = thresholds
        self._risk_weights = risk_weights
        self._default_risk_weight = default_risk_weight
        self._critical_gap_threshold_pct = critical_gap_threshold_pct
        self._significant_gap_threshold_pct = significant_gap_threshold_pct
        self._system_prompt = system_prompt

    def get_subgraph(self) -> ComplianceGapWorkflowGraph:
        from src.graph.domain_workflow_graph import ComplianceGapWorkflowGraph

        return ComplianceGapWorkflowGraph(
            config={
                "llm": self._llm_config,
                "timeout_s": self._timeout_s,
                "thresholds": self._thresholds,
                "risk_weights": self._risk_weights,
                "default_risk_weight": self._default_risk_weight,
                "critical_gap_threshold_pct": self._critical_gap_threshold_pct,
                "significant_gap_threshold_pct": self._significant_gap_threshold_pct,
                "system_prompt": self._system_prompt,
            }
        )

    def extract_input(self, state: AgentState) -> str:
        # validated_input is the normalized JSON string built by
        # CompletionDataIngestNode — the single string the inner
        # BaseGraph.invoke() boundary requires (docs/02_design.md).
        return str(state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        output = sub_result.get("output", {}) or {}
        if not isinstance(output, dict):
            output = {}
        return {
            "threshold_results": output.get("threshold_results", []),
            "gap_classifications": output.get("gap_classifications", []),
            "priority_ranked": output.get("priority_ranked", []),
            "gap_report_markdown": output.get("gap_report_markdown", ""),
            "status": sub_result.get("status"),
        }


class ComplianceTrainingCompletionTrackingGapReportAgent(AgentBaseGraph):
    """EDU-C2-025 — compliance training completion gap tracking & reporting."""

    @property
    def name(self) -> str:
        return "ComplianceTrainingCompletionTrackingGapReportAgent"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        super()._validate_config()
        try:
            validate_gap_config(self.config)
        except ValueError as exc:
            raise ConfigError(f"[{self.__class__.__name__}] invalid compliance policy config: {exc}") from exc

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode

        self._nodes["pre_process"] = CompletionDataIngestNode()
        self._nodes["main"] = ComplianceGapWorkflowGraphNode(
            llm_config=self.config.get("llm"),
            timeout_s=self.config.get("timeout_s", 120),
            thresholds=self.config.get("thresholds"),
            risk_weights=self.config.get("risk_weights"),
            default_risk_weight=self.config.get("default_risk_weight", 3.0),
            critical_gap_threshold_pct=self.config.get("critical_gap_threshold_pct", 15.0),
            significant_gap_threshold_pct=self.config.get("significant_gap_threshold_pct", 5.0),
            system_prompt=self.config.get("system_prompt"),
        )
        self._nodes["post_process"] = OutputValidateNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
