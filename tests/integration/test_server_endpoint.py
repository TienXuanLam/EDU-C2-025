# EDU-C2-025 — Integration Tests: HTTP entry point (endpoint-level trust gate)
#
# Uses FastAPI's TestClient against the real src.api.server.app — no live
# socket, but exercises the actual /invoke handler (INVOKE_AUTH_TOKEN check,
# ctx construction, agent.invoke()) rather than only unit-testing individual
# nodes. Complements tests/unit/test_output_validate_node.py's node-level
# trust-gate test (unit tests can't prove the endpoint itself enforces auth).

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("INVOKE_AUTH_TOKEN", "test-endpoint-token")
    # Re-import fresh so the module-level `agent`/token read happens under
    # this fixture's env var (src.api.server reads INVOKE_AUTH_TOKEN
    # per-request inside the handler, not at import time, so a plain import
    # is sufficient here — no importlib.reload needed).
    from src.api.server import app

    return TestClient(app)


def _payload(mode: str = "deterministic_only") -> dict:
    return {
        "input": json.dumps(
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
        ),
        "session_id": "test-session",
    }


def test_health_endpoint_no_auth_required(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_invoke_without_token_returns_401(client):
    """Anonymous caller with no bearer token must be rejected at the
    entry-point boundary (before any node runs), not silently downgraded."""
    resp = client.post("/invoke", json=_payload())
    assert resp.status_code == 401


def test_invoke_with_wrong_token_returns_401(client):
    resp = client.post("/invoke", json=_payload(), headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_invoke_with_correct_token_reaches_the_agent(client):
    """With a valid bearer token the caller runs at VERIFIED_EXTERNAL and the
    request reaches the agent. deterministic_only mode needs no LLM, so this
    also proves the full pipeline (no Azure OpenAI secrets configured in this
    test environment) succeeds end-to-end via the real HTTP entry point."""
    resp = client.post(
        "/invoke", json=_payload("deterministic_only"), headers={"Authorization": "Bearer test-endpoint-token"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "InitializeNode" in body["node_history"]
    assert "CompletionDataIngestNode" in body["node_history"]


def test_invoke_full_report_under_stg_mock_mode_succeeds(client, monkeypatch):
    """full_report mode (the LLM-drafted path) succeeds end-to-end through the
    real HTTP entry point when STG_MOCK_MODE=true, with no Azure OpenAI
    secrets provisioned — proves ReportDraftNode._build_llm()'s mock branch is
    correctly wired all the way from /invoke."""
    monkeypatch.setenv("STG_MOCK_MODE", "true")
    resp = client.post("/invoke", json=_payload("full_report"), headers={"Authorization": "Bearer test-endpoint-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert "OutputValidateNode" in body["node_history"]  # post_process ran on the LLM-drafted output
