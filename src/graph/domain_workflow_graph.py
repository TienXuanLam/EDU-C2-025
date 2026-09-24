"""AgentCore Platform v1.0"""

# EDU-C2-025 — inner domain workflow graph (Cat 2, see docs/02_design.md).
# Instantiated by ComplianceGapWorkflowGraphNode.get_subgraph() in graph.py.
# Inherits BaseGraph directly — fully custom topology, not the
# pre_process/main/post_process backbone (that belongs to the outer graph).
#
# Pipeline (branches once, on mode — proposal has no >1 mode, but the LLM
# narrative step (report_draft) needs a bypass so the agent can be exercised
# without a real LLM/API key, e.g. Stage 5 STG smoke test — see
# docs/02_design.md "deterministic_only mode"):
#     START -> threshold_check -> gap_classify -> risk_priority_score -> {route: mode}
#                full_report:          -> report_draft -> END
#                deterministic_only:   -> END (OutputValidateNode renders the
#                                              already-computed data directly)

from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.errors import ConfigError
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from src.nodes.gap_classify_node import GapClassifyNode
from src.nodes.report_draft_node import ReportDraftNode
from src.nodes.risk_priority_score_node import RiskPriorityScoreNode
from src.nodes.threshold_check_node import ThresholdCheckNode
from src.schemas.state import State
from src.services.compliance_gap_service import validate_gap_config


class ComplianceGapWorkflowGraph(BaseGraph):
    """Inner graph for the 4-step compliance-gap scoring and report drafting workflow."""

    @property
    def name(self) -> str:
        return "compliance_gap_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        try:
            validate_gap_config(self.config)
        except ValueError as exc:
            raise ConfigError(f"[{self.__class__.__name__}] invalid compliance policy config: {exc}") from exc

    def register_nodes(self) -> None:
        thresholds = self.config.get("thresholds") or {}
        risk_weights = self.config.get("risk_weights") or {}
        default_risk_weight = self.config.get("default_risk_weight", 3.0)
        critical_gap_threshold_pct = self.config.get("critical_gap_threshold_pct", 15.0)
        significant_gap_threshold_pct = self.config.get("significant_gap_threshold_pct", 5.0)
        system_prompt = self.config.get("system_prompt")

        self._nodes["threshold_check"] = ThresholdCheckNode(thresholds)
        self._nodes["gap_classify"] = GapClassifyNode(critical_gap_threshold_pct, significant_gap_threshold_pct)
        self._nodes["risk_priority_score"] = RiskPriorityScoreNode(risk_weights, default_risk_weight)
        # "llm" in config is a tuning dict (temperature/max_tokens), never a
        # client instance — ReportDraftNode builds its own secret-bound
        # AzureOpenAIClient per invocation via _build_llm(state).
        self._nodes["report_draft"] = ReportDraftNode(
            system_prompt=system_prompt,
            llm_config=self.config.get("llm"),
            timeout_s=self.config.get("timeout_s", 120),
        )

    def add_edges(self) -> None:
        self._sg.add_edge(START, "threshold_check")
        self._sg.add_edge("threshold_check", "gap_classify")
        self._sg.add_edge("gap_classify", "risk_priority_score")
        # lambda wrapper, not a bare `self.route` reference: passing the bound
        # method directly to add_conditional_edges (langgraph==1.1.10) caused
        # BOTH conditional targets to fire regardless of the returned value
        # (reproduced with a minimal StateGraph outside this class) — the
        # lambda wrapper does not exhibit the bug.
        self._sg.add_conditional_edges(
            "risk_priority_score",
            lambda state: self.route(state),
            {"report_draft": "report_draft", END: END},
        )
        self._sg.add_edge("report_draft", END)

    def route(self, state: AgentState) -> str:
        """Conditional routing after risk_priority_score.

        deterministic_only mode skips the LLM narrative step entirely —
        OutputValidateNode (outer post_process) renders priority_ranked
        directly instead (docs/02_design.md).
        """
        if state.get("status") == AgentStatus.ERROR.value:
            return END
        return "report_draft" if state.get("mode") == "full_report" else END

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "output": {
                "reporting_period": state.get("reporting_period", ""),
                "threshold_results": state.get("threshold_results", []),
                "gap_classifications": state.get("gap_classifications", []),
                "priority_ranked": state.get("priority_ranked", []),
                "gap_report_markdown": state.get("gap_report_markdown", ""),
            },
            "status": state.get("status", AgentStatus.ERROR.value),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
