"""AgentCore Platform v1.0"""

# State fields are flat primitives / containers of primitives only (see
# sdk/concepts/state-and-schemas.md) — msgpack-checkpoint-safe. No employee
# names, employee IDs, or other individual identifiers of any kind ever land
# here — only aggregated completion-rate records (proposal §3).

from typing import Any

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """EDU-C2-025 — ComplianceTrainingCompletionTrackingGapReportAgent state.

    Only fields specific to this agent are declared below. Shared fields
    (user_input, status, session_id, node_history, error_log, hitl_*, etc.)
    are inherited from AgentState.
    """

    # --- pre_process (CompletionDataIngestNode) ---
    mode: str  # "full_report" (LLM narrative) | "deterministic_only" (no LLM)
    reporting_period: str
    records: list[dict[str, Any]]  # aggregated completion records

    # --- main (ComplianceGapWorkflowGraphNode <- inner domain workflow graph) ---
    threshold_results: list[dict[str, Any]]  # + threshold, gap_pct, below_threshold
    gap_classifications: list[dict[str, Any]]  # + severity
    priority_ranked: list[dict[str, Any]]  # + risk_score, rank (sorted, gap items first)
    gap_report_markdown: str

    # --- post_process (OutputValidateNode) ---
    final_report_markdown: str
