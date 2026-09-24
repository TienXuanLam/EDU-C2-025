# EDU-C2-025 — Compliance Training Completion Tracking Gap Report Agent

> **Category**: Cat 2 (orchestrates multiple steps to accomplish a specific use case)
> **Industry**: EDU (education)

## Overview

Receives aggregated compliance-training completion-rate data from a compliance/HR
officer (training domain, business unit, role category, period, completion
percentage — never individual employee names, IDs, or per-employee records) and
produces a management-ready, audit-grade Markdown gap report: which units/domains fall
below their configured completion-rate threshold, how severe each gap is
(critical/significant/advisory), and a regulatory-risk-weighted priority ranking, plus
a narrative executive summary and priority actions.

**The bundled completion-rate thresholds, risk weights, and severity band cutoffs in
`config/config.yaml` are illustrative starting values, not sourced regulatory data.**
They are not taken from MHLW / CPPC / Fair Trade Commission guidance or any real
company's regulatory risk appetite. Review and override them before relying on the
generated report for audit or disclosure purposes. PII exclusion is a regex/key-name
heuristic, not a certified PII detector — it rejects known forbidden field names and
identifier-shaped values, but does not exhaustively detect every identifier format.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |
| Azure OpenAI | A resource with a chat-capable deployment — `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` |

```bash
pip install -e .
```

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and operational documentation
```

See `docs/` for the design spec and test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
