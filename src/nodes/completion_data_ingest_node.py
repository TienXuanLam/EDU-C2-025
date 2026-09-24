"""AgentCore Platform v1.0"""

# Outer pre_process node (docs/02_design.md — proposal step 1:
# CompletionDataIngest). Parses the aggregated completion-rate JSON payload,
# validates it, and normalizes it into validated_input (a JSON string) for the
# inner domain workflow graph (GraphNode.extract_input() can only forward a
# single string — see docs/02_design.md State Definition note).

from __future__ import annotations

import json
import math
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.individual_identifier_scan import contains_individual_identifier

_VALID_MODES = {"full_report", "deterministic_only"}
_REQUIRED_RECORD_FIELDS = ("training_domain", "business_unit", "role_category", "completion_rate")
_MAX_SHORT_FIELD_LEN = 200
_MAX_RECORDS_COUNT = 500  # a quarterly consolidation across many units/domains, still bounded


class CompletionDataIngestNode(FunctionNode):
    """Validate and normalize the incoming aggregated completion-rate request."""

    # S-1: compliance/HR officer caller only — not anonymous public.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_input(self, state: AgentState) -> AgentState:
        """S-2 domain check: reject payloads carrying individual-level data.

        Proposal §3: individual employee names, IDs, and individual
        completion records are rejected at S-1 (this hook is the concrete
        enforcement — aggregated data only).
        """
        raw = state.get("user_input", "") or ""
        if contains_individual_identifier(raw):
            state = dict(state)
            state["status"] = AgentStatus.ERROR.value
            state["error_log"] = list(state.get("error_log", [])) + [
                "CompletionDataIngestNode: input rejected — apparent individual-level "
                "identifier detected (this template accepts aggregated data only)"
            ]
        return state

    @staticmethod
    def _parse_and_validate(raw: str) -> tuple[dict[str, Any] | None, str | None]:
        """Return (normalized_payload, None) on success, or (None, error_message)."""
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return None, "user_input is not valid JSON"

        if not isinstance(payload, dict):
            return None, "user_input JSON must be an object"

        mode = payload.get("mode", "full_report")
        if mode not in _VALID_MODES:
            return None, f"invalid mode {mode!r}"

        reporting_period = payload.get("reporting_period")
        if not reporting_period or not isinstance(reporting_period, str):
            return None, "missing required field: reporting_period"
        if len(reporting_period) > _MAX_SHORT_FIELD_LEN:
            return None, f"reporting_period exceeds max length ({_MAX_SHORT_FIELD_LEN} chars)"
        if any(ord(char) < 32 for char in reporting_period):
            return None, "reporting_period contains control characters"

        records = payload.get("records")
        if not isinstance(records, list):
            return None, "records must be a list, not " + type(records).__name__
        if not records:
            return None, "records must contain at least one entry"
        if len(records) > _MAX_RECORDS_COUNT:
            return None, f"records exceeds max count ({_MAX_RECORDS_COUNT})"

        normalized_records: list[dict[str, Any]] = []
        for idx, record in enumerate(records):
            if not isinstance(record, dict):
                return None, f"records[{idx}] must be an object"

            missing = [f for f in _REQUIRED_RECORD_FIELDS if f not in record]
            if missing:
                return None, f"records[{idx}] missing required field(s): {missing}"

            for field in ("training_domain", "business_unit", "role_category"):
                value = record[field]
                if not isinstance(value, str) or not value.strip():
                    return None, f"records[{idx}].{field} must be a non-empty string"
                if len(value) > _MAX_SHORT_FIELD_LEN:
                    return None, f"records[{idx}].{field} exceeds max length ({_MAX_SHORT_FIELD_LEN} chars)"
                if any(ord(char) < 32 for char in value):
                    return None, f"records[{idx}].{field} contains control characters"

            completion_rate = record["completion_rate"]
            if isinstance(completion_rate, bool):  # bool is an int subclass — reject explicitly
                return None, f"records[{idx}].completion_rate must be a number, not a boolean"
            if not isinstance(completion_rate, (int, float)):
                return None, f"records[{idx}].completion_rate must be a number"
            normalized_rate = float(completion_rate)
            if not math.isfinite(normalized_rate):
                return None, f"records[{idx}].completion_rate must be finite"
            if not (0.0 <= normalized_rate <= 100.0):
                return None, f"records[{idx}].completion_rate must be between 0 and 100, got {completion_rate}"

            normalized_records.append(
                {
                    "training_domain": str(record["training_domain"]),
                    "business_unit": str(record["business_unit"]),
                    "role_category": str(record["role_category"]),
                    "completion_rate": normalized_rate,
                }
            )

        return {
            "mode": mode,
            "reporting_period": str(reporting_period),
            "records": normalized_records,
        }, None

    def execute(self, state: AgentState) -> dict[str, Any]:
        if state.get("status") == AgentStatus.ERROR.value:
            # Already rejected by the S-2 hook above.
            return {"status": AgentStatus.ERROR.value}

        normalized, error = self._parse_and_validate(state.get("user_input", "") or "")
        if error:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [f"CompletionDataIngestNode: {error}"],
            }

        assert normalized is not None

        emit_trace_event(
            "completion_data_ingested",
            {"reporting_period": normalized["reporting_period"], "record_count": len(normalized["records"])},
            state,
        )

        return {
            **normalized,
            "validated_input": json.dumps(normalized),
            "status": AgentStatus.SUCCESS.value,
        }
