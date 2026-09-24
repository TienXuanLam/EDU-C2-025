"""Standalone server dependency injection and trust-boundary tests."""

import importlib

import pytest

_AZURE_SECRETS = {
    "AZURE_OPENAI_API_KEY": "dummy-test-key",
    "AZURE_OPENAI_ENDPOINT": "https://example.services.ai.azure.com",
    "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
}


def test_server_boots_without_azure_openai_secrets(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    monkeypatch.delenv("STG_MOCK_MODE", raising=False)
    import src.api.server as server

    importlib.reload(server)
    assert server.app is not None
    assert server.agent is not None


class TestServerProvisionsInvocationSecrets:
    """server.py's InMemoryProvider construction must merge os.environ with
    the configured provider (namespace="EDU"), preferring os.environ -- this
    is what makes `podman/docker run -e AZURE_OPENAI_...` work when testing a
    built image locally, the same fleet-standard pattern used elsewhere in
    the fleet's server.py files. LLM credentials are
    resolved per-invocation inside ReportDraftNode via
    InvocationContext.from_state(state).secrets.require(...), not built once
    at server startup.
    """

    def test_configured_provider_reaches_standalone_secret_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from shared.secrets.inmemory_provider import InMemoryProvider

        for key in _AZURE_SECRETS:
            monkeypatch.delenv(key, raising=False)

        monkeypatch.setattr(
            "shared.secrets.factory",
            lambda namespace, agent_name: InMemoryProvider(_AZURE_SECRETS),
        )

        import src.api.server as server

        importlib.reload(server)

        assert {key: server._secrets_provider.require(key) for key in _AZURE_SECRETS} == _AZURE_SECRETS

    def test_process_environment_reaches_standalone_secret_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key, value in _AZURE_SECRETS.items():
            monkeypatch.setenv(key, value)

        import src.api.server as server

        importlib.reload(server)

        assert {key: server._secrets_provider.require(key) for key in _AZURE_SECRETS} == _AZURE_SECRETS


def test_stg_mock_mode_returns_deterministic_llm(monkeypatch):
    monkeypatch.setenv("STG_MOCK_MODE", "true")
    from src.nodes.report_draft_node import ReportDraftNode, _MockLLM

    node = ReportDraftNode()
    llm = node._build_llm({})
    assert isinstance(llm, _MockLLM)


def test_standalone_tokens_have_distinct_trust_levels():
    import src.api.server as server
    from framework.schemas.trust_level import TrustLevel

    assert (
        server._resolve_standalone_trust(TrustLevel.ANONYMOUS, "Bearer external", "external", "runner")
        is TrustLevel.VERIFIED_EXTERNAL
    )
    assert (
        server._resolve_standalone_trust(TrustLevel.ANONYMOUS, "Bearer runner", "external", "runner")
        is TrustLevel.INTERNAL
    )
