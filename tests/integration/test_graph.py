# EDU-C2-025 — Integration Tests: full outer graph (BL-46..BL-53)

import json

import pytest
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from shared.secrets.inmemory_provider import InMemoryProvider

from src.graph.domain_workflow_graph import ComplianceGapWorkflowGraph
from src.graph.graph import ComplianceGapWorkflowGraphNode, ComplianceTrainingCompletionTrackingGapReportAgent
from src.nodes.output_validate_node import DISCLAIMER
from src.nodes.report_draft_node import ReportDraftNode

THRESHOLDS = {"harassment_prevention": 90.0, "occupational_safety": 95.0}
RISK_WEIGHTS = {"harassment_prevention": 4.0, "occupational_safety": 5.0}


def _verified_ctx() -> InvocationContext:
    # pre_process / post_process require VERIFIED_EXTERNAL (docs/02_design.md S-1)
    return InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


class FakeLLM:
    """Matches shared.services.llm.base_llm.BaseLLM.complete() — takes a
    message list, returns the canonical {"content": ..., "tool_calls": [],
    "model": ...} dict. Records every messages list it was called with, so
    tests can assert on prompt content (e.g. Config Surface fields)."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def complete(self, messages: list) -> dict:
        self.calls.append(messages)
        return {"content": "## Executive Summary\nDraft report.", "tool_calls": [], "model": "fake"}


@pytest.fixture
def agent(monkeypatch):
    # ReportDraftNode now builds its own LLM per invocation via _build_llm(state)
    # rather than accepting a constructor-injected client — patch the bound
    # method at the class level so every instance the graph constructs
    # returns this fixture's FakeLLM.
    fake_llm = FakeLLM()
    monkeypatch.setattr(ReportDraftNode, "_build_llm", lambda self, state: fake_llm)
    a = ComplianceTrainingCompletionTrackingGapReportAgent(
        config={"thresholds": THRESHOLDS, "risk_weights": RISK_WEIGHTS, "max_retry": 1}
    )
    a.compile()
    return a


@pytest.fixture
def secrets():
    return InMemoryProvider({})


def _payload(mode: str = "full_report") -> str:
    return json.dumps(
        {
            "mode": mode,
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


def test_full_report_mode(agent, secrets):
    """BL-46: full_report mode produces an LLM-drafted report with disclaimer."""
    with bound_secrets(secrets):
        result = agent.invoke(_payload("full_report"), ctx=_verified_ctx())

    assert result["status"] == "success"
    assert "Executive Summary" in result["output"]
    assert DISCLAIMER.strip("\n") in result["output"]


def test_deterministic_only_mode(agent, secrets):
    """BL-47: deterministic_only mode skips the LLM step and renders the table directly."""
    with bound_secrets(secrets):
        result = agent.invoke(_payload("deterministic_only"), ctx=_verified_ctx())

    assert result["status"] == "success"
    assert "Per-Unit Completion Table" in result["output"]
    assert "harassment_prevention" in result["output"]


def test_invalid_input_returns_error(agent, secrets):
    with bound_secrets(secrets):
        result = agent.invoke("not valid json", ctx=_verified_ctx())

    assert result["status"] == "error"


class UnsafeFakeLLM:
    """Simulates an LLM that leaks an apparent individual identifier — the
    scenario S-3 exists to catch (LLM output is not proposal-guaranteed
    clean, even though upstream data is aggregated only)."""

    def complete(self, messages: list) -> dict:
        return {
            "content": "Employee ID 00231 has not completed the training.",
            "tool_calls": [],
            "model": "fake-unsafe",
        }


def test_full_pipeline_blocks_unsafe_generated_content(secrets, monkeypatch):
    """End-to-end: an LLM that leaks an apparent individual identifier must
    not reach the caller as a successful gap report. Complements the
    OutputValidateNode-only unit test with the full outer-graph lifecycle."""
    unsafe_llm = UnsafeFakeLLM()
    monkeypatch.setattr(ReportDraftNode, "_build_llm", lambda self, state: unsafe_llm)
    a = ComplianceTrainingCompletionTrackingGapReportAgent(config={"thresholds": THRESHOLDS, "max_retry": 1})
    a.compile()
    with bound_secrets(secrets):
        result = a.invoke(_payload("full_report"), ctx=_verified_ctx())

    assert result["status"] == "error"
    assert result["output"] is None


def test_inner_graph_deterministic_only_skips_report_draft_node(secrets):
    """Regression test: the outer agent's node_history only ever shows the 4
    outer nodes (InitializeNode/.../FinalizeNode) — it cannot see which inner
    nodes ran, so it can't catch a routing bug where deterministic_only
    silently falls through to report_draft anyway. Assert directly on the
    inner graph's own node_history instead (mirrors a real langgraph==1.1.10
    bound-method routing bug regression test used elsewhere in the fleet)."""
    inner = ComplianceGapWorkflowGraph(config={"thresholds": THRESHOLDS})
    inner.compile()
    validated_input = json.dumps(
        {
            "mode": "deterministic_only",
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
    with bound_secrets(secrets):
        result = inner.invoke(validated_input, ctx=_verified_ctx())

    assert result["node_history"] == ["ThresholdCheckNode", "GapClassifyNode", "RiskPriorityScoreNode"]
    assert result["status"] == "success"  # no LLM needed for this mode


def test_inner_graph_full_report_runs_all_four_nodes(secrets, monkeypatch):
    fake_llm = FakeLLM()
    monkeypatch.setattr(ReportDraftNode, "_build_llm", lambda self, state: fake_llm)
    inner = ComplianceGapWorkflowGraph(config={"thresholds": THRESHOLDS})
    inner.compile()
    validated_input = json.dumps(
        {
            "mode": "full_report",
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
    with bound_secrets(secrets):
        result = inner.invoke(validated_input, ctx=_verified_ctx())

    assert result["node_history"] == [
        "ThresholdCheckNode",
        "GapClassifyNode",
        "RiskPriorityScoreNode",
        "ReportDraftNode",
    ]
    assert result["status"] == "success"


def test_config_surface_reaches_nodes(secrets, monkeypatch):
    """Config Surface (proposal §10): thresholds / risk_weights / severity
    bands / system_prompt must actually reach the running nodes, not just
    exist as unread config.yaml keys."""
    fake_llm = FakeLLM()
    monkeypatch.setattr(ReportDraftNode, "_build_llm", lambda self, state: fake_llm)
    inner = ComplianceGapWorkflowGraph(
        config={
            "thresholds": {"harassment_prevention": 90.0},
            "risk_weights": {"harassment_prevention": 9.0},
            "critical_gap_threshold_pct": 5.0,  # low bar -> even a small gap is "critical"
            "significant_gap_threshold_pct": 1.0,
            "system_prompt": "TEST-SYSTEM-PROMPT",
        }
    )
    inner.compile()
    validated_input = json.dumps(
        {
            "mode": "full_report",
            "reporting_period": "FY2026-Q2",
            "records": [
                {
                    "training_domain": "harassment_prevention",
                    "business_unit": "Sales",
                    "role_category": "manager",
                    "completion_rate": 85.0,  # 5pt gap vs threshold 90
                }
            ],
        }
    )
    with bound_secrets(secrets):
        result = inner.invoke(validated_input, ctx=_verified_ctx())

    assert result["status"] == "success"
    # critical_gap_threshold_pct=5.0: a 5pt gap crosses into "critical"
    assert result["output"]["gap_classifications"][0]["severity"] == "critical"
    # risk_weights: 9.0 * 5.0 = 45.0
    assert result["output"]["priority_ranked"][0]["risk_score"] == 45.0
    # system_prompt: threaded as the system-role message
    all_system_prompts = " ".join(m["content"] for call in fake_llm.calls for m in call if m["role"] == "system")
    assert "TEST-SYSTEM-PROMPT" in all_system_prompts


def test_graph_node_trust_gate_lifecycle(secrets):
    """ComplianceGapWorkflowGraphNode (a GraphNode) lives in src/graph/graph.py,
    not src/nodes/ — PB-6's discovery only scans src/nodes/, so this node's
    S-1/S-4 __call__ lifecycle has no other coverage. Exercised directly via
    __call__(), not only indirectly through the outer agent."""
    node = ComplianceGapWorkflowGraphNode(thresholds=THRESHOLDS)

    anonymous_state = {
        "caller_trust_level": TrustLevel.ANONYMOUS.value,
        "correlation_id": "x",
        "session_id": "x",
        "thread_id": "x",
        "trace_id": "",
        "hitl_allowed": True,
        "node_history": [],
        "error_log": [],
    }
    denied = node(anonymous_state)
    assert denied["status"] == "error"

    validated_input = json.dumps(
        {
            "mode": "deterministic_only",
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
    verified_state = {
        **anonymous_state,
        "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
        "validated_input": validated_input,
    }
    with bound_secrets(secrets):
        allowed = node(verified_state)
    assert allowed["status"] == "success"
    assert "ComplianceGapWorkflowGraphNode" in allowed["node_history"]
