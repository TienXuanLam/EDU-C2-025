"""Standalone HTTP adapter for EDU-C2-025."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from framework.utils.config_loader import load_config
from shared.secrets import factory as secrets_factory
from shared.secrets.inmemory_provider import InMemoryProvider
from src.graph.graph import ComplianceTrainingCompletionTrackingGapReportAgent

app = FastAPI(title="Agent")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def _load_runtime_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or _CONFIG_PATH
    return dict(load_config(str(path))) if path.exists() else {}


_runtime_config = _load_runtime_config()
# Standalone Podman/Docker runs inject secrets through process environment,
# while the configured provider covers platform-managed execution. Merge both
# channels into the invocation-scoped provider without exposing secret values
# to state or telemetry -- ReportDraftNode resolves the Azure OpenAI secrets
# per-invocation through InvocationContext, not from this module-level
# provider directly.
_configured_secrets_provider = secrets_factory(
    namespace="EDU",
    agent_name="ComplianceTrainingCompletionTrackingGapReportAgent",
)
_azure_secret_keys = ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT")
_secrets_provider = InMemoryProvider(
    {
        key: value
        for key in _azure_secret_keys
        if (value := os.environ.get(key) or _configured_secrets_provider.get(key)) is not None
    },
    namespace="EDU",
    agent_name="ComplianceTrainingCompletionTrackingGapReportAgent",
)
# LLM construction is no longer wired here: ReportDraftNode builds its own
# secret-bound AzureOpenAIClient per invocation via _build_llm(state) — see
# its docstring. config["llm"] (from config.yaml) is only a tuning dict
# (temperature/max_tokens), never a client instance, never read by this
# module.

agent = ComplianceTrainingCompletionTrackingGapReportAgent(config=_runtime_config)
_hitl_enabled = bool(agent.config.get("hitl", {}).get("enabled", False))
_needs_checkpointer = bool(agent.config.get("memory_enabled")) or _hitl_enabled
agent.compile(checkpointer=MemorySaver() if _needs_checkpointer else None)
agent.provision_secrets(_secrets_provider)


class InvokeRequest(BaseModel):
    input: str
    session_id: str = ""


def _bearer_matches(supplied: str, expected: str) -> bool:
    return secrets.compare_digest(supplied.encode(), f"Bearer {expected}".encode())


def _resolve_standalone_trust(
    current: TrustLevel,
    authorization: str,
    invoke_auth_token: str | None,
    internal_runner_token: str | None,
) -> TrustLevel:
    if current is not TrustLevel.ANONYMOUS:
        return current
    if internal_runner_token and _bearer_matches(authorization, internal_runner_token):
        return TrustLevel.INTERNAL
    if invoke_auth_token and _bearer_matches(authorization, invoke_auth_token):
        return TrustLevel.VERIFIED_EXTERNAL
    if internal_runner_token or invoke_auth_token:
        raise HTTPException(status_code=401, detail="Token is invalid or expired.")
    return TrustLevel.ANONYMOUS


@app.post("/invoke")
async def invoke(req: InvokeRequest, request: Request) -> dict[str, Any]:
    trust = _resolve_standalone_trust(
        getattr(request.state, "trust_level", TrustLevel.ANONYMOUS),
        request.headers.get("authorization", ""),
        os.environ.get("INVOKE_AUTH_TOKEN"),
        os.environ.get("STG_INTERNAL_RUNNER_TOKEN"),
    )
    with bound_secrets(agent._secrets_provider):
        ctx = InvocationContext(
            session_id=req.session_id or str(uuid4()),
            caller_trust_level=trust,
            caller_id=getattr(request.state, "caller_id", ""),
        )
        return cast(dict[str, Any], agent.invoke(req.input, ctx=ctx))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "ComplianceTrainingCompletionTrackingGapReportAgent"}
