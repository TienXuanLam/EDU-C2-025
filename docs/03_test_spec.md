# Test Specification

## Test Strategy
- Coverage target: all business logic paths (success + validation-rejection + fail-closed) per node/service
- Test types: Unit (nodes, services), Integration (outer graph, inner graph, HTTP entry point), Proof-of-Boundary (framework contract)

## Scope Disclaimer

`config/config.yaml`'s `thresholds` and `risk_weights` are illustrative starting values, not
sourced regulatory guidance (see README.md Known Limitations, docs/02_design.md). Tests verify
the *mechanism* (threshold comparison, severity banding, weighted scoring/ranking) is correct
given whatever values are configured — they do not and cannot verify the illustrative default
values themselves are regulatorily accurate.

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | ✅ `src/schemas/state.py` — all fields `str`/`list[dict]` |
| TC-02 | SecurityViolationError fires on invalid input | S-2 rejection sets `status=error` (framework convention); S-3 raises `RuntimeError` | ✅ `test_completion_data_ingest_node.py::test_s2_rejects_individual_identifier_via_call`, `test_output_validate_node.py::test_s3_rejects_unsafe_output` |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations | ✅ no credential fields declared |
| TC-04 | InvocationContext via configurable only | Not exercised by any node (docs/02_design.md Framework Utilization) | N/A — no node calls `InvocationContext.from_state()` |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start`/`node_complete`/`node_error` absent from `execute()` body | ✅ manual review — only `emit_trace_event()` domain events |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` at class definition if overridden | ✅ 0 overrides — all nodes extend via `_extra_security_gate_input()` only |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` at class definition if overridden | ✅ 0 overrides |
| TC-08 | `required_trust_level` enforced | Insufficient trust → refused | ✅ `test_output_validate_node.py::test_trust_gate_rejects_anonymous_caller`, `test_graph.py::test_graph_node_trust_gate_lifecycle` |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial | Individual-identifier key/email scan on the raw payload | ✅ `CompletionDataIngestNode._extra_security_gate_input` |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial | Individual-identifier text/email scan on the finalized report | ✅ `OutputValidateNode._extra_security_gate_output` |
| TC-11 | S-4: ≥1 domain `emit_trace_event()` per `execute()`, on the success path | Domain event emitted on the success path of every node | ✅ every node calls `emit_trace_event()` on success — correction (eng-moderator T2-01, LOW, 2026-07-20): a prior revision of this row read "every invocation path," which overstates coverage. `CompletionDataIngestNode.execute()` returns before `completion_data_ingested` fires when the S-2 gate or `_parse_and_validate()` rejects the input (`src/nodes/completion_data_ingest_node.py:115-131`); `ReportDraftNode.execute()` likewise returns before `gap_report_drafted` fires when no LLM is configured, the provider call raises, or the response is blank (`src/nodes/report_draft_node.py:77-106`). No domain event is emitted on any of these rejection paths — only on success. The framework's own `node_start`/`node_complete`/`node_error` lifecycle events (S-4, distinct from these domain events — see TC-05) fire unconditionally regardless of node outcome; PB-1/PB-6 below verify those. |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | Framework `node_start`/`node_complete`/`node_error` lifecycle events fire on every invocation path | No silent failures | ✅ — this is the framework's own lifecycle event emission, not the domain `emit_trace_event()` calls in `src/nodes/`, which only fire on each node's success path (see TC-11 correction above) |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | ✅ `test_state_safety.py` |
| PB-3 | Level 2 → External service | Real external service connection | N/A — this template has no external service beyond the LLM (no KB, no DB) | N/A |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | ✅ `test_import_isolation.py` |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | ✅ `test_state_safety.py` |
| PB-6 | Invoke execution order | S-1 → S-4 `node_start` → S-2 → `execute()` → S-3 → S-4 `node_complete` | Order verified | ✅ `test_pb_invoke_order.py` (discovers all 6 `src/nodes/` classes dynamically) |
| PB-7 | HITL interrupt propagation *(conditional)* | `hitl.enabled` absent from `config/config.yaml` | **Auto-waived — non-HITL** | ✅ 2 SKIPPED |

> **Pre-CoE gate checklist:** PB-1 through PB-6 are mandatory (PB-3 N/A per this template's
> architecture — no external service beyond the LLM). PB-7 auto-waived — non-HITL.

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01..04 | `individual_identifier_scan` — structured JSON scan | Clean payload / forbidden key / email / malformed JSON | Correctly flags only individual-level data | ✅ `test_individual_identifier_scan.py::TestContainsIndividualIdentifier` |
| BL-02..03 | `individual_identifier_scan` — free-text scan | Clean prose / employee ID cue / email | Correctly flags only individual-level data in LLM output | ✅ `TestContainsIndividualIdentifierText` |
| BL-05..07 | `check_threshold` | Below / at-threshold / unconfigured domain | Correct `below_threshold`/`gap_pct`/`threshold` per case | ✅ `test_compliance_gap_service.py::TestCheckThreshold` |
| BL-08..10 | `classify_severity` | unconfigured / compliant / critical / significant / advisory | Correct severity tier per band | ✅ `TestClassifySeverity` |
| BL-10 | `classify_severity` boundary | gap_pct exactly at a band cutoff | Inclusive — belongs to the higher-severity band | ✅ `test_band_boundary_is_inclusive` |
| BL-11..14 | `score_and_rank` | Mixed gap/non-gap items, missing risk_weight | Correct score, rank, and ordering | ✅ `TestScoreAndRank` |
| BL-15..27 | `CompletionDataIngestNode` | Valid/malformed/missing-field/out-of-range/boolean-coercion/oversized/invalid-mode payloads | Correct accept/reject per case; S-2 hook rejects individual data | ✅ `test_completion_data_ingest_node.py` |
| BL-28..30 | `ThresholdCheckNode` | Forwarded JSON rehydration, unconfigured domain, empty thresholds | Correct rehydration and pass-through; no crash | ✅ `test_threshold_check_node.py` |
| BL-31..32 | `GapClassifyNode` | Mixed threshold_results, empty list | Correct per-item severity; no crash | ✅ `test_gap_classify_node.py` |
| BL-33..34 | `RiskPriorityScoreNode` | Mixed gap/non-gap classifications, empty list | Correct score/rank; no crash | ✅ `test_risk_priority_score_node.py` |
| BL-35..38 | `ReportDraftNode` | LLM success / missing secret / provider exception / empty content | Fail-closed on every non-success path | ✅ `test_report_draft_node.py` |
| BL-39..45 | `OutputValidateNode` | full_report / deterministic_only / critical escalation / unsafe output / trust gate | Correct rendering per mode; S-3 blocks unsafe output; trust gate enforced | ✅ `test_output_validate_node.py` |
| BL-46..53 | Outer + inner graph integration | full_report / deterministic_only / invalid input / unsafe LLM / config surface / GraphNode trust gate | End-to-end correctness; regression coverage for inner-graph routing (mirrors a real langgraph==1.1.10 bound-method bug found elsewhere in the fleet) | ✅ `test_graph.py` |
| — | HTTP entry point | No token / wrong token / correct token | 401/401/200 with correct `node_history` | ✅ `test_server_endpoint.py` |

## Test Execution Summary
- Execution date: 2026-08-20
- Migrated suite: 86 collected (82 passed, 4 skipped — PB-7, the optional
  Anthropic-extra injection case when unavailable, and the conditional
  pre-checkpoint ingress case)
- Pass: 82 / Fail: 0 / Skip: 4
- Coverage: all node `execute()` success + primary rejection paths; all `compliance_gap_service.py`
  pure functions; S-1/S-2/S-3/S-4 lifecycle for every node type (`FunctionNode` and `GraphNode`)
