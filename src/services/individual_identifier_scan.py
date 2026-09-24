"""AgentCore Platform v1.0"""

# S-2 domain check (CompletionDataIngestNode._extra_security_gate_input): this
# template only accepts aggregated completion-rate data (proposal §3) — never
# individual employee names, IDs, or emails. Two independent checks:
#   1. forbidden key names on any parsed "records" entry (structural check —
#      catches a caller who sends per-employee rows instead of aggregates)
#   2. an email-address pattern anywhere in the raw payload text (catches an
#      identifier embedded in a value rather than a key, e.g. business_unit
#      accidentally set to a person's email)
# Mirrors the same identifier-scan role used elsewhere in the fleet, applied
# to this template's very different (structured, not narrative) input shape.

from __future__ import annotations

import json
import re

_FORBIDDEN_KEYS = frozenset(
    {
        "employee_name",
        "name",
        "full_name",
        "employee_id",
        "individual_id",
        "user_id",
        "staff_id",
        "personnel_id",
        "student_name",
        "email",
    }
)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+")
_NUMERIC_IDENTIFIER_RE = re.compile(r"\b\d{6,12}\b")

# Free-text cue phrases used by _contains_individual_identifier_text() — the
# LLM-generated report is prose, not structured JSON, so the key-name check
# above does not apply; scan for the same "individual-level data" concept
# expressed as text instead (defense-in-depth at S-3 — OutputValidateNode).
_TEXT_CUE_RE = re.compile(r"(?i:employee\s*(name|id)|staff\s*id|personnel\s*id|social\s*security|\bSSN\b)")


def contains_individual_identifier(raw_input: str) -> bool:
    """Return True if raw_input (JSON text) appears to carry individual-level data."""
    if _EMAIL_RE.search(raw_input or "") or _NUMERIC_IDENTIFIER_RE.search(raw_input or ""):
        return True

    try:
        payload = json.loads(raw_input) if (raw_input or "").strip() else {}
    except json.JSONDecodeError:
        return False  # malformed JSON is CompletionDataIngestNode.execute()'s problem, not S-2's

    records = payload.get("records")
    if not isinstance(records, list):
        return False

    for record in records:
        if not isinstance(record, dict):
            continue
        if any(str(key).strip().lower() in _FORBIDDEN_KEYS for key in record):
            return True

    return False


def contains_individual_identifier_text(text: str) -> bool:
    """S-3 defense-in-depth: scan LLM-generated prose (not structured JSON)
    for signs it leaked individual-level data despite upstream aggregation."""
    text = text or ""
    return bool(_EMAIL_RE.search(text) or _NUMERIC_IDENTIFIER_RE.search(text) or _TEXT_CUE_RE.search(text))
