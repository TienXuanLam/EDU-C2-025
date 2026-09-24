# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `ComplianceTrainingCompletionTrackingGapReportAgent`
- **L1 Base**: `AgentBaseGraph`
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible), `src/schemas/state.py`
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

The approved proposal lists six steps —
CompletionDataIngest, ThresholdCheck, GapClassify, RiskPriorityScore, ReportDraft,
OutputValidate — more than `AgentBaseGraph`'s three fixed slots (`pre_process` / `main` /
`post_process`). Per the current scaffold convention (`src/examples/graph_cat2_sample.py`,
supersedes the older step-helper pattern described in some historical playbook notes), the
four middle steps are encapsulated in an inner `BaseGraph` wrapped by a `GraphNode` in the
outer `main` slot:

```
Outer graph (src/graph/graph.py):
    AgentBaseGraph — fixed backbone, add_edges() NOT overridden.
    pre_process  = CompletionDataIngestNode        (proposal step 1)
    main         = ComplianceGapWorkflowGraphNode   (GraphNode wrapping the inner graph)
    post_process = OutputValidateNode                (proposal step 6)

Inner graph (src/graph/domain_workflow_graph.py):
    ComplianceGapWorkflowGraph(BaseGraph) — fully custom topology.
    threshold_check (step 2) -> gap_classify (step 3) -> risk_priority_score (step 4)
        -> {route: mode} -> report_draft (step 5, LLM) -> END
                          -> END directly (deterministic_only mode — see below)
```

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | schema_version, session_id, trust_level | — | — | InitializeNode (default) |
| pre_process | `CompletionDataIngestNode` — parse/validate aggregated JSON payload, reject individual-level identifiers (S-2) | `user_input` | `mode`, `reporting_period`, `records`, `validated_input` | FunctionNode |
| main | `ComplianceGapWorkflowGraphNode` — wraps the inner 4-step graph | `validated_input` | `threshold_results`, `gap_classifications`, `priority_ranked`, `gap_report_markdown` | GraphNode |
| ↳ threshold_check | Compare each record's completion_rate against `config/config.yaml` `thresholds` | `user_input` (forwarded JSON) | `threshold_results` | FunctionNode (inner) |
| ↳ gap_classify | Three-tier severity classification from gap_pct bands | `threshold_results` | `gap_classifications` | FunctionNode (inner) |
| ↳ risk_priority_score | Score (`risk_weight × gap_pct`) and rank | `gap_classifications` | `priority_ranked` | FunctionNode (inner) |
| ↳ report_draft | LLM-draft a non-numeric executive narrative; render table, ranked actions, and escalation flags deterministically (skipped in `deterministic_only` mode) | `priority_ranked`, `reporting_period` | complete `gap_report_markdown` | FunctionNode (inner) |
| post_process | `OutputValidateNode` — attach mandatory disclaimer, render deterministic fallback when `deterministic_only`, S-3 re-scan | `gap_report_markdown` or `priority_ranked` | `final_report_markdown`, `formatted_output` | FunctionNode |
| finalize | response_metadata, total_time_ms | — | — | FinalizeNode (default) |

### Data Flow

```
START → initialize → pre_process → main → {route} → post_process → finalize → END
                                            ↓ (retry)
                                          pre_process
```

### `deterministic_only` mode — not in the source proposal, added during implementation

The source review doc's workflow always ends in an LLM report-drafting step (step 5), with
no LLM-free path. That makes the pipeline impossible to exercise end-to-end (Stage ⑤ STG
smoke test / CI `run-tests`) without real `AZURE_OPENAI_*` secrets. Mirroring an
`alignment_check_only`-style precedent used elsewhere in the fleet, `CompletionDataIngestNode` accepts an optional `mode` field
(`"full_report"` default, or `"deterministic_only"`): in `deterministic_only` mode the inner
graph routes straight from `risk_priority_score` to `END`, skipping `report_draft` entirely,
and `OutputValidateNode` renders the already-computed `priority_ranked` data directly into
the same report shape instead of an LLM narrative. This is also a genuinely useful standalone
capability (a compliance officer can get the raw ranked gap table without waiting on/paying
for an LLM call), not only a test-support shim.

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `mode` | `str` | `"full_report"` (LLM narrative) or `"deterministic_only"` (no LLM) | pre_process |
| `reporting_period` | `str` | Caller-supplied period label (e.g. `"FY2026-Q2"`) | pre_process |
| `records` | `list[dict]` | Normalized aggregated records: `training_domain`, `business_unit`, `role_category`, `completion_rate` | pre_process |
| `threshold_results` | `list[dict]` | `records` + `threshold`, `gap_pct`, `below_threshold` | main (inner: threshold_check) |
| `gap_classifications` | `list[dict]` | `threshold_results` + `severity` (`critical`/`significant`/`advisory`/`compliant`/`unconfigured_domain`) | main (inner: gap_classify) |
| `priority_ranked` | `list[dict]` | `gap_classifications` + `risk_score`, `rank` (gap items ranked first) | main (inner: risk_priority_score) |
| `gap_report_markdown` | `str` | LLM executive narrative plus deterministically rendered facts/ranking (empty in `deterministic_only` mode) | main (inner: report_draft) |
| `final_report_markdown` | `str` | Final report + mandatory disclaimer | post_process |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types) — `records`/`*_results`/`*_ranked`
  are `list[dict]` of primitives only, no nested objects.
- No JWT, API keys, credentials in State (checkpoint DB leakage).
- No employee names, employee IDs, or other individual identifiers in State (proposal §3) —
  enforced by `CompletionDataIngestNode._extra_security_gate_input()` (S-2) and
  `OutputValidateNode._extra_security_gate_output()` (S-3).
- `InvocationContext` rule: `ReportDraftNode._build_llm(state)` obtains
  `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_DEPLOYMENT` via
  `InvocationContext.from_state(state)` inside `execute()` only, per invocation, and never
  stores them in State (see Framework Utilization below).
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible).

## Framework Utilization

### Shared Components Used
- [x] `InvocationContext.from_state(state)` — used by `ReportDraftNode._build_llm(state)` to
      resolve `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_DEPLOYMENT` per
      invocation, never at graph-construction time. A client built once at server startup and
      cached on a shared node instance would be reused across every caller for the process
      lifetime — a credential-rotation/multi-tenant-isolation hazard.
      `STG_MOCK_MODE=true` makes `_build_llm()` return a deterministic `_MockLLM` instead, for
      STG-tier wiring tests only.
- [ ] ConnectionPolicy (retry/timeout strategy) — not used; no external service beyond the LLM.
- [ ] SecurityViolationError — not explicitly raised; S-2 rejection sets `status=ERROR` +
      `error_log` (framework convention per `customize-security-gates.md`), S-3 rejection
      raises `RuntimeError` (matches an `OutputValidateNode` precedent used elsewhere in the fleet).
- [x] S-2: `_extra_security_gate_input()` — `CompletionDataIngestNode` rejects any payload
      whose `records` entries carry a forbidden individual-identifier key (`employee_name`,
      `employee_id`, `email`, etc.) or whose raw text contains an email-address pattern
      (`src/services/individual_identifier_scan.py::contains_individual_identifier`).
- [x] S-3: `_extra_security_gate_output()` — `OutputValidateNode` re-scans the finalized
      report text for the same individual-identifier signal, expressed as free-text cue
      phrases this time since the output is prose, not structured JSON
      (`contains_individual_identifier_text`) — defense-in-depth in case the LLM (full_report
      mode) invents a per-employee breakdown despite only ever seeing aggregated data.
- [x] S-4: `emit_trace_event()` — every node emits at least one domain event on its success path
      (`completion_data_ingested`, `thresholds_checked`, `gaps_classified`,
      `gaps_scored_and_ranked`, `gap_report_drafted`, `gap_report_finalized`). This is
      success-path domain-event coverage, not "every invocation path" (eng-moderator T2-01,
      LOW, 2026-07-20): `CompletionDataIngestNode.execute()` returns before
      `completion_data_ingested` fires on a rejected request, and `ReportDraftNode.execute()`
      returns before `gap_report_drafted` fires when no LLM is configured, the provider call
      raises, or the response is blank — no domain event fires on any of these paths. See
      `docs/03_test_spec.md` TC-11 correction. The framework's own
      `node_start`/`node_complete`/`node_error` lifecycle events (distinct from these domain
      events) do fire unconditionally on every path.

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

### Composition Pattern

- **Pattern**: GraphNode (subgraph) — `ComplianceGapWorkflowGraphNode` wraps
  `ComplianceGapWorkflowGraph` (inner `BaseGraph`).
- **Composition target**: `src/graph/domain_workflow_graph.py`
- **Error propagation strategy**: `propagate` (default) — an inner-graph error surfaces as
  `SubgraphError` in the outer graph; fail fast, no silent partial gap report.

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only (no `agents/base/` required)

## Known Limitation — Threshold/Risk-Weight Values Are Illustrative, Not Sourced Regulatory Data

`config/config.yaml`'s `thresholds` and `risk_weights` dicts are illustrative defaults chosen
by the implementing engineer to make the pipeline runnable end-to-end — they are NOT sourced
from MHLW / CPPC / Fair Trade Commission guidance or any real company's actual regulatory risk
appetite. The severity band cutoffs (`critical_gap_threshold_pct`, `significant_gap_threshold_pct`)
are equally illustrative. See README.md Known Limitations. Every deploying company must review
and override these values before relying on the generated report for audit or
securities-disclosure purposes — this matches the source proposal's own Risk #3 mitigation
("customizable in YAML config so each company can adjust to their own legal risk
prioritization").

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Fixed 6-step pipeline determined entirely by input data — no autonomous think→act loop needed |
| Composition pattern | Step-helper (pure-Python, 3 `FunctionNode`s) | GraphNode + inner `BaseGraph` | **GraphNode + inner graph** | Current scaffold convention (`src/examples/graph_cat2_sample.py`); matches a precedent used elsewhere in the fleet |
| Threshold/severity/scoring logic location | LLM-arbitrated (single ReportDraft prompt does everything) | Deterministic Python (`compliance_gap_service.py`), LLM only for prose | **Deterministic Python** | Which units are below threshold, how severe, and how ranked are regulatory-risk-material judgments — must not be LLM-arbitrated, same principle as an `AlignmentCheckNode` precedent used elsewhere in the fleet |
| LLM-free execution path | None (always require LLM) | Add `deterministic_only` mode | **Added `deterministic_only` mode** | Without it, the pipeline cannot be exercised in CI/Stage ⑤ STG without real Azure OpenAI secrets; also independently useful (raw ranked table without LLM cost/latency) |
| Unconfigured `training_domain` handling | Hard reject at ingest | Flag as `unconfigured_domain`, still process | **Flag, don't reject** | A domain-name typo should not silently drop a whole business unit's data; the officer needs to see it needs configuring (proposal §11 Risk #2 mitigation: "config update handles revisions without code changes") |
