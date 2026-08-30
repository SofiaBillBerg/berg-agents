"""Provider-agnostic LLM contract for the OAP-inspired layer.

Defines ``LLMProvider`` (the structural protocol every concrete provider -
ollama, openai, ... - must satisfy) and ``ProviderBase`` (a convenient ABC
that implements the protocol's ``bind_capabilities`` default). No concrete
model backend is referenced here; providers are selected by config via
``providers/registry.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class LLMProvider(Protocol):
    """Structural contract every LLM provider must satisfy.

    Attributes:
        name: Stable provider identifier, e.g. ``"ollama"`` or ``"openai"``.
    """

    name: str

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Generate a completion for the given chat ``messages``.

        :param messages: Chat history as a list of ``{"role": ..., "content": ...}`` message dicts.
        :return: The model's text completion.
        """
        ...

    def bind_capabilities(self, caps: list[Any]) -> LLMProvider:
        """Return a provider bound to the given capabilities.

        Providers that need tool-binding (e.g. function calling) may return a
        new provider instance configured with ``caps``; others return ``self``.

        :param caps: Capabilities available to the provider.

        :return: A provider instance bound to ``caps``.
        """
        ...


class ProviderBase(ABC):
    """Base class for LLM providers (ollama, openai, openrouter ...).

    Subclasses must set ``name`` and implement ``complete``. ``bind_capabilities``
    defaults to a no-op that returns ``self``; providers that require tool-binding
    override it.

    :ivar name: Stable provider identifier, e.g. ``"ollama"`` or ``"openai"``.
    :ivar model: The model name, e.g. ``"qwen3.5"`` or ``"gpt-4o"``.
    :ivar temperature: Sampling temperature, ``0.0`` to ``1.0``.
    :ivar max_tokens: Maximum number of tokens to generate.
    :ivar stream: Whether to stream the response.
    :ivar api_key: API key for the provider.
    :ivar base_url: Base URL for the provider.
    :ivar capabilities: Capabilities available to the provider.
    """

    name: str = "base"

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Generate a completion for the given chat ``messages``.

        :param messages: Chat history as a list of ``{"role": ..., "content": ...}``
                message dicts.
        :return: The model's text completion.
        """
        ...

    def bind_capabilities(self, caps: list[Any]) -> ProviderBase:
        """Return a provider bound to the given capabilities.

        Providers that need tool-binding (e.g. function calling) may return a
        new provider instance configured with ``caps``; others return ``self``.

        :param caps: Capabilities available to the provider.
        :return: A provider instance bound to ``caps``.
        """
        return self
