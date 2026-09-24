"""Deterministic rendering of compliance-gap facts and rankings."""

from __future__ import annotations

from typing import Any


def _cell(value: object) -> str:
    """Escape caller-controlled values before placing them in Markdown tables."""
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def render_report(
    reporting_period: str,
    priority_ranked: list[dict[str, Any]],
    executive_summary: str | None = None,
) -> str:
    """Render authoritative numeric sections from deterministic state.

    The optional LLM text is isolated to Executive Summary. It cannot replace
    or alter the computed completion table, priority order, or escalation list.
    """
    gap_items = [item for item in priority_ranked if item.get("rank") is not None]
    other_items = [item for item in priority_ranked if item.get("rank") is None]
    escalation_items = [item for item in gap_items if item.get("severity") == "critical"]

    summary = (
        executive_summary.strip()
        if executive_summary
        else (
            "Deterministic-only mode: no LLM narrative was generated. Review the "
            "authoritative computed sections below."
        )
    )
    lines = [
        f"# Compliance Training Gap Report: {_cell(reporting_period)}",
        "",
        "## Executive Summary",
        "",
        summary,
        "",
        "## Per-Unit Completion Table",
        "",
        "| Training Domain | Business Unit | Role Category | Completion Rate | Threshold | Severity |",
        "|---|---|---|---|---|---|",
    ]
    for item in priority_ranked:
        threshold = "N/A" if item.get("threshold") is None else f"{_cell(item.get('threshold'))}%"
        lines.append(
            f"| {_cell(item.get('training_domain', ''))} | {_cell(item.get('business_unit', ''))} | "
            f"{_cell(item.get('role_category', ''))} | {_cell(item.get('completion_rate', ''))}% | "
            f"{threshold} | {_cell(item.get('severity', ''))} |"
        )

    lines += ["", "## Priority Actions"]
    if gap_items:
        for item in gap_items:
            lines.append(
                f"{_cell(item.get('rank'))}. [{_cell(item.get('severity'))}] "
                f"{_cell(item.get('training_domain'))} / {_cell(item.get('business_unit'))} / "
                f"{_cell(item.get('role_category'))} — gap {_cell(item.get('gap_pct'))} pts "
                f"(risk_score {_cell(item.get('risk_score'))})"
            )
    else:
        lines.append("(none — no unit/domain is below its configured threshold)")

    lines += ["", "## Escalation Flags"]
    if escalation_items:
        for item in escalation_items:
            lines.append(
                f"- {_cell(item.get('training_domain'))} / {_cell(item.get('business_unit'))} / "
                f"{_cell(item.get('role_category'))}"
            )
    else:
        lines.append("(none)")

    unconfigured = [item for item in other_items if item.get("severity") == "unconfigured_domain"]
    if unconfigured:
        lines += ["", "## Unconfigured Domains (no threshold in config/config.yaml)"]
        for item in unconfigured:
            lines.append(
                f"- {_cell(item.get('training_domain'))} / {_cell(item.get('business_unit'))} / "
                f"{_cell(item.get('role_category'))}"
            )

    return "\n".join(lines)
