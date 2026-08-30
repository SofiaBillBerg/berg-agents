"""Tests for the provider-agnostic LLM layer.

Covers the ``LLMProvider`` protocol and ``ProviderBase``
(:mod:`berg_agents.providers.base`), the config-driven model registry
(:mod:`berg_agents.providers.registry`) and the ``ModelProvider``
adapter (:mod:`berg_agents.providers.provider`).

The adapter is built directly on ``langchain.init_chat_model``; provider
construction is lazy and ``complete()`` is exercised against a mocked
client, so no network calls are made during the tests.
"""

from __future__ import annotations

from abc import ABC
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from berg_agents.providers.base import LLMProvider, ProviderBase
from berg_agents.providers.provider import ModelProvider
from berg_agents.providers.registry import (
    build_llm,
    list_models,
    load_providers,
    resolve_model,
)


# ---------------------------------------------------------------------------
# Dummy providers used by the protocol tests (no network)
# ---------------------------------------------------------------------------


class DummyProvider:
    """Minimal structural match for the ``LLMProvider`` protocol."""

    name: str = "dummy"

    # ruff: ignore[no-self-use]
    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Return a canned completion."""
        return "dummy response"

    def bind_capabilities(self, caps: list[Any]) -> DummyProvider:
        """Return self (no tool-binding needed)."""
        return self


class IncompleteProvider:
    """Provider missing ``complete``; must not satisfy the protocol."""

    name: str = "incomplete"

    def bind_capabilities(self, caps: list[Any]) -> IncompleteProvider:
        """Return self (no tool-binding needed)."""
        return self


class EchoProvider(ProviderBase):
    """Concrete ``ProviderBase`` subclass that only implements ``complete``."""

    name: str = "echo"

    # ruff: ignore[no-self-use]
    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Return a canned completion."""
        return "echo"


# ---------------------------------------------------------------------------
# LLMProvider protocol (runtime_checkable structural contract)
# ---------------------------------------------------------------------------


def test_dummy_provider_satisfies_llm_provider_protocol() -> None:
    """A class with name/complete/bind_capabilities must match the protocol."""
    assert isinstance(DummyProvider(), LLMProvider)


def test_incomplete_provider_does_not_satisfy_protocol() -> None:
    """A provider missing ``complete`` must not match the protocol."""
    assert not isinstance(IncompleteProvider(), LLMProvider)


def test_concrete_adapters_satisfy_llm_provider_protocol() -> None:
    """The shipped adapter must structurally satisfy the protocol."""
    assert isinstance(ModelProvider(model="m", api_key="k"), LLMProvider)


# ---------------------------------------------------------------------------
# ProviderBase (ABC with a no-op bind_capabilities default)
# ---------------------------------------------------------------------------


def test_provider_base_bind_capabilities_returns_self() -> None:
    """The default bind_capabilities must be a no-op returning self."""
    provider = EchoProvider()
    assert provider.bind_capabilities([object()]) is provider


def test_provider_base_requires_complete_implementation() -> None:
    """``complete`` is abstract; a subclass without it must not instantiate."""

    class MissingComplete(ProviderBase, ABC):
        """Subclass that forgets to implement ``complete``."""

        name: str = "broken"

    with pytest.raises(TypeError):
        MissingComplete()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Registry: load_providers
# ---------------------------------------------------------------------------

#: Two arbitrary OpenAI-compatible providers — proves there is no hardcoding.
SAMPLE_PROVIDERS: dict[str, Any] = {
    "ollama": {
        "name": "ollama(Local)",
        "options": {"baseURL": "http://localhost:11435/v1"},
        "models": {
            "qwen3.5:9b": {},
            "mistral:latest": {
                "options": {"baseURL": "http://localhost:11436/v1"}
            },
        },
    },
    "omniroute": {
        "name": "omniroute",
        "options": {
            "baseURL": "http://localhost:20128/v1",
            "apiKey": "{env:OMNIROUTE_API_KEY}",
        },
        "models": {"auto": {}, "best-free": {}},
    },
}


def test_load_providers_returns_configured_block() -> None:
    """The raw ``providers`` block from config must pass through untouched."""
    assert load_providers({"providers": SAMPLE_PROVIDERS}) == SAMPLE_PROVIDERS


def test_load_providers_synthesizes_from_legacy_flat_keys() -> None:
    """Legacy ollama_*/openai_* configs must synthesize a registry."""
    cfg = {
        "ollama_scheme": "http",
        "ollama_host": "localhost",
        "ollama_port": 11434,
        "ollama_model": "gpt-oss:20b",
        "openai_model": "gpt-4o",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_api_key": "k",
    }
    providers = load_providers(cfg)
    assert "ollama" in providers and "omniroute" in providers
    assert "gpt-oss:20b" in providers["ollama"]["models"]


def test_load_providers_empty_config_yields_empty_registry() -> None:
    """A config with neither block nor legacy keys yields no providers."""
    assert load_providers({}) == {}


# ---------------------------------------------------------------------------
# Registry: resolve_model (provider derived FROM the model)
# ---------------------------------------------------------------------------


def test_resolve_model_uses_own_provider_options() -> None:
    """An Ollama model must resolve to its own baseURL — never another's."""
    resolved = resolve_model("qwen3.5:9b", {"providers": SAMPLE_PROVIDERS})
    assert resolved["model"] == "qwen3.5:9b"
    assert resolved["_provider"] == "ollama"
    assert resolved["base_url"] == "http://localhost:11435/v1"
    # api_key always present and empty by default (Ollama ignores keys).
    assert not resolved["api_key"]


def test_resolve_model_omniroute_gets_its_url_and_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different provider's model resolves to that provider's options."""
    monkeypatch.setenv("OMNIROUTE_API_KEY", "secret-123")
    resolved = resolve_model("best-free", {"providers": SAMPLE_PROVIDERS})
    assert resolved["_provider"] == "omniroute"
    assert resolved["base_url"] == "http://localhost:20128/v1"
    assert resolved["api_key"] == "secret-123"


def test_resolve_model_missing_env_placeholder_becomes_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r"""An unset {env:VAR} placeholder expands to an empty string."""
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    resolved = resolve_model("auto", {"providers": SAMPLE_PROVIDERS})
    assert not resolved["api_key"]


def test_resolve_model_per_model_options_override_provider() -> None:
    """Per-model options must win over the provider-level defaults."""
    resolved = resolve_model("mistral:latest", {"providers": SAMPLE_PROVIDERS})
    assert resolved["base_url"] == "http://localhost:11436/v1"


def test_resolve_model_none_returns_first_declared_default() -> None:
    """Without an explicit id the first declared model is the default."""
    resolved = resolve_model(None, {"providers": SAMPLE_PROVIDERS})
    assert resolved["model"] == "qwen3.5:9b"


def test_resolve_model_unknown_id_raises_keyerror_listing_known() -> None:
    """Unknown ids must raise KeyError naming every known model."""
    with pytest.raises(KeyError) as excinfo:
        resolve_model("nope", {"providers": SAMPLE_PROVIDERS})
    message = str(excinfo.value)
    assert "qwen3.5:9b" in message
    assert "best-free" in message


# ---------------------------------------------------------------------------
# Registry: build_llm / list_models
# ---------------------------------------------------------------------------


def test_build_llm_creates_concrete_chat_openai_client() -> None:
    """build_llm must produce a concrete client at the right base_url."""
    resolved = resolve_model("qwen3.5:9b", {"providers": SAMPLE_PROVIDERS})
    llm = build_llm(resolved)
    # Every OpenAI-compatible backend resolves to ChatOpenAI.
    assert type(llm).__name__ == "ChatOpenAI"
    assert str(
        getattr(llm, "openai_api_base", getattr(llm, "base_url", ""))
    ).endswith("11435/v1")


def test_build_llm_has_no_configurable_fields_proxy() -> None:
    """build_llm must return a real BaseChatModel, not the lazy proxy."""
    resolved = resolve_model("auto", {"providers": SAMPLE_PROVIDERS})
    llm = build_llm(resolved)
    assert type(llm).__name__ != "_ConfigurableModel"


def test_list_models_lists_every_declared_model() -> None:
    """list_models must return one entry per declared model."""
    models = list_models({"providers": SAMPLE_PROVIDERS})
    ids = {m["model"] for m in models}
    assert ids == {"qwen3.5:9b", "mistral:latest", "auto", "best-free"}
    by_model = {m["model"]: m for m in models}
    assert by_model["qwen3.5:9b"]["provider"] == "ollama"
    assert by_model["best-free"]["provider"] == "omniroute"


# ---------------------------------------------------------------------------
# ModelProvider adapter (mocked client, no network)
# ---------------------------------------------------------------------------


def test_model_provider_complete_returns_content() -> None:
    """``complete`` must return the client response content."""
    provider = ModelProvider(model="gpt-4o", api_key="k")
    client = MagicMock()
    client.invoke.return_value = SimpleNamespace(content="hi there")
    provider._client = client
    messages = [{"role": "user", "content": "hi"}]
    assert provider.complete(messages) == "hi there"
    client.invoke.assert_called_once_with(messages)


def test_model_provider_complete_wraps_backend_errors() -> None:
    """Backend failures must surface as a RuntimeError from ``complete``."""
    provider = ModelProvider(model="gpt-4o", api_key="k")
    client = MagicMock()
    client.invoke.side_effect = RuntimeError("backend down")
    provider._client = client
    with pytest.raises(RuntimeError, match="Completion failed"):
        provider.complete([{"role": "user", "content": "hi"}])


def test_model_provider_bind_capabilities_returns_self() -> None:
    """The adapter must not rebind capabilities."""
    provider = ModelProvider(model="m", api_key="k")
    assert provider.bind_capabilities([object()]) is provider


# noinspection unnecessary-cast
def test_model_provider_defaults_to_empty_api_key() -> None:
    r"""Missing api_key must default to an empty secret so keyless backends work."""
    provider = ModelProvider(model="gpt-4o")
    assert not cast(Any, provider.api_key).get_secret_value()


# noinspection unnecessary-cast
def test_model_provider_explicit_api_key_is_kept() -> None:
    """An explicitly provided api_key must be stored as-is."""
    provider = ModelProvider(model="gpt-4o", api_key="explicit")
    assert cast(Any, provider.api_key).get_secret_value() == "explicit"
