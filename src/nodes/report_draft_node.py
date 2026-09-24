"""AgentCore Platform v1.0"""

# Inner domain workflow node (docs/02_design.md — proposal step 5:
# ReportDraft). LLM-generates the executive summary, per-unit table, priority
# actions, and escalation recommendations narrative. The underlying
# severity/score/rank numbers are already deterministically computed upstream
# (ThresholdCheckNode/GapClassifyNode/RiskPriorityScoreNode) — this node only
# turns that structured data into prose; it never re-derives or overrides the
# severity/rank judgment itself (Design Decision Record, docs/02_design.md).

from __future__ import annotations

import os
import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.services.llm.azure_openai_client import AzureOpenAIClient
from shared.services.llm.base_llm import BaseLLM
from shared.utils.audit_logger import emit_trace_event
from src.services.llm_helper import complete_text
from src.services.report_render_service import render_report

_ESCALATION_SEVERITIES = ("critical",)
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^#{1,6}\s")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_NUMERIC_FIELDS = ("completion_rate", "threshold", "gap_pct", "risk_score", "rank")


def _allowed_numbers(reporting_period: str, priority_ranked: list[dict[str, Any]]) -> set[str]:
    """Every number that legitimately appears in the already-computed data.

    A real LLM narrates the supplied facts back (e.g. "completion stood at
    82.5% against a 90.0% threshold" or "a risk score of 30") rather than
    reproducing every value verbatim — that is not "inventing" a number, so
    a blanket "any digit is an error" check (this function's caller used to
    run) rejects every real LLM response while only ever passing a
    hand-written FakeLLM in tests. Only a number NOT present in the source
    data indicates the LLM fabricated something. Both the exact string form
    (e.g. "30.0") and, for whole-number floats, the trimmed form ("30") are
    allowed, since an LLM naturally drops a trailing ".0" in prose. Numbers
    embedded in reporting_period (e.g. "FY2026-Q2" -> "2026", "2") are also
    legitimate — an LLM restating the period it was asked to report on is
    not fabrication either.
    """
    allowed: set[str] = set(_NUMBER_RE.findall(reporting_period))
    for item in priority_ranked:
        for field in _NUMERIC_FIELDS:
            value = item.get(field)
            if value is None:
                continue
            allowed.add(str(value))
            if isinstance(value, float) and value.is_integer():
                allowed.add(str(int(value)))
    return allowed


def _contains_fabricated_number(summary: str, reporting_period: str, priority_ranked: list[dict[str, Any]]) -> bool:
    allowed = _allowed_numbers(reporting_period, priority_ranked)
    return any(match not in allowed for match in _NUMBER_RE.findall(summary))


class _MockLLM(BaseLLM):
    """STG_MOCK_MODE=true stand-in -- deterministic, no network call.

    STG-tier wiring tests only; must never be reachable in production (see
    STG_MOCK_MODE handling in ReportDraftNode._build_llm()).
    """

    def complete(self, _messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {"content": "STG_MOCK_MODE stand-in response — not a real LLM response."}

    def stream(self, _messages: list[Any]) -> Any:
        raise NotImplementedError("_MockLLM: stream() is not used by ReportDraftNode")

    def bind_tools(self, _tools: list[Any]) -> BaseLLM:
        raise NotImplementedError("_MockLLM: bind_tools() is not used by ReportDraftNode")


def _build_prompt(reporting_period: str, priority_ranked: list[dict[str, Any]]) -> str:
    gap_items = [i for i in priority_ranked if i.get("rank") is not None]
    escalation_items = [i for i in gap_items if i.get("severity") in _ESCALATION_SEVERITIES]
    other_items = [i for i in priority_ranked if i.get("rank") is None]

    def _fmt(item: dict[str, Any]) -> str:
        return (
            f"- [{item.get('severity')}] rank {item.get('rank')}: {item.get('training_domain')} / "
            f"{item.get('business_unit')} / {item.get('role_category')} — "
            f"completion {item.get('completion_rate')}% vs threshold {item.get('threshold')}% "
            f"(gap {item.get('gap_pct')} pts, risk_score {item.get('risk_score')})"
        )

    def _fmt_other(item: dict[str, Any]) -> str:
        return (
            f"- [{item.get('severity')}]: {item.get('training_domain')} / {item.get('business_unit')} / "
            f"{item.get('role_category')} — completion {item.get('completion_rate')}%"
        )

    gap_lines = "\n".join(_fmt(i) for i in gap_items) or "(none — no unit/domain is below its configured threshold)"
    escalation_lines = "\n".join(_fmt(i) for i in escalation_items) or "(none)"
    other_lines = "\n".join(_fmt_other(i) for i in other_items) or "(none)"

    return (
        f"Reporting period: {reporting_period}\n\n"
        "Below is the already-computed, ranked list of compliance training gaps "
        "(highest regulatory risk first) for this period:\n"
        f"{gap_lines}\n\n"
        "Items flagged for escalation (critical severity):\n"
        f"{escalation_lines}\n\n"
        "Other units/domains (compliant or no threshold configured):\n"
        f"{other_lines}\n\n"
        "Draft only a concise executive-summary narrative. Do not reproduce tables, "
        "rankings, action lists, or escalation lists; those sections are rendered "
        "deterministically from the computed records. Use only the supplied facts and "
        "do not invent people, units, domains, or numbers."
    )


class ReportDraftNode(FunctionNode):
    """LLM-draft the management-ready gap report from the ranked gap data."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        system_prompt: str | None = None,
        llm_config: dict[str, Any] | None = None,
        timeout_s: int = 120,
    ) -> None:
        super().__init__()
        self._system_prompt = system_prompt
        self._llm_config = dict(llm_config or {})
        self._timeout_s = timeout_s

    def _build_llm(self, state: AgentState) -> BaseLLM:
        """Build a fresh, secret-bound LLM client for this invocation.

        Constructor-time injection (an `llm` param threaded through
        config["llm"] at graph-construction time) depends on server.py
        building the client once, at module-import time, and caching it on
        this node instance for the lifetime of the process — every
        subsequent invocation, from every caller, would share that one
        client (a credential-rotation/multi-tenant-isolation hazard).
        Building the client per-invocation here instead reads secrets from
        `state` at call time via InvocationContext, and never stores a
        client on `self`.

        STG_MOCK_MODE=true returns a deterministic _MockLLM instead of a
        real client -- STG-tier wiring tests only, must never be set in
        production. This is the scaffold's standard Stage 5
        provisional-deploy toggle, set "true" by the shared deploy-stg CI
        job.
        """
        if os.environ.get("STG_MOCK_MODE", "").lower() == "true":
            return _MockLLM()
        ctx = InvocationContext.from_state(state)
        return AzureOpenAIClient(
            {
                "api_key": ctx.secrets.require("AZURE_OPENAI_API_KEY"),
                "azure_endpoint": ctx.secrets.require("AZURE_OPENAI_ENDPOINT"),
                "azure_deployment": ctx.secrets.require("AZURE_OPENAI_DEPLOYMENT"),
                "timeout": self._timeout_s,
                **self._llm_config,
            }
        )

    def execute(self, state: AgentState) -> dict[str, Any]:
        reporting_period = state.get("reporting_period", "")
        priority_ranked = state.get("priority_ranked", [])

        prompt = _build_prompt(reporting_period, priority_ranked)
        try:
            llm = self._build_llm(state)
            raw_response = complete_text(llm, prompt, self._system_prompt)
        except Exception as exc:  # provider/network/secret error — fail closed, not a crash
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"ReportDraftNode: LLM request failed: {exc}"],
            }

        if not raw_response.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["ReportDraftNode: LLM returned empty content"],
            }

        summary = raw_response.strip()
        if summary.startswith("## Executive Summary"):
            summary = summary.removeprefix("## Executive Summary").strip()
        if (
            not summary
            or _contains_fabricated_number(summary, reporting_period, priority_ranked)
            or _MARKDOWN_HEADING_RE.search(summary)
        ):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    (
                        "ReportDraftNode: LLM summary must not invent numbers absent from the "
                        "supplied data or inject additional report sections"
                    )
                ],
            }

        emit_trace_event(
            "gap_report_drafted",
            {
                "reporting_period": reporting_period,
                "gap_item_count": len([i for i in priority_ranked if i.get("rank")]),
            },
            state,
        )

        report = render_report(reporting_period, priority_ranked, executive_summary=summary)
        return {
            "gap_report_markdown": report,
            "status": AgentStatus.SUCCESS.value,
        }
