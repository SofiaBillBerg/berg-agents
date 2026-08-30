"""LLM provider for the OAP-inspired layer.

Wraps ``langchain.init_chat_model`` behind the provider-agnostic
``LLMProvider`` contract so business logic never references a concrete
model backend directly. The model name, API key and base URL are read
from constructor arguments (the API key falls back to the
``BERG_AGENT_API_KEY`` environment variable), never hardcoded.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from berg_agents.providers.base import ProviderBase
from langchain.chat_models import init_chat_model
from pydantic import SecretStr

class ModelProvider(ProviderBase):
    """LLM provider.

    Attributes:
        :ivar model: model name, e.g. ``"gpt-4o"``.
        :ivar api_key: API key as a :class:`pydantic.SecretStr`, or ``None`` when read from ``*_API_KEY``.
        :ivar base_url: Optional base URL for the API, e.g. for proxies or emulators such as ``"https://api.openai.com/v1"``, ``"http://localhost:1234/v1"``.
    """

    provider: str = "openai"

    def __init__(
        self,
        model: str,
        api_key: str | Callable[[], str] | None = "",
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the model provider.

        :param model: model name to use for completions.
        :param api_key: API key. Defaults to ``""`` so OpenAI-compatible
            backends that ignore keys (e.g. local Ollama) keep working;
            pass a key only when the endpoint requires one.
        :param base_url: Optional base URL for the API, e.g. when using a proxy or service emulator.
        :param **kwargs: Extra options forwarded to the underlying chat model, e.g. ``temperature``, ``max_tokens``, ``stream``.
        :return: The initialized provider.
        """
        if api_key is None:
            # Never break on a missing key — providers that ignore it are
            # common; an empty string is sent as the bearer token instead.
            api_key = ""

        # Store as SecretStr so the key never leaks via repr/logging.
        self.api_key = (
            SecretStr(api_key) if isinstance(api_key, str) else api_key
        )

        self.model = model
        self.base_url = base_url

        #  accepts SecretStr directly; pass it through so the
        # underlying SDK handles redaction without extra conversion.
        # NOTE: no configurable_fields — this is always a concrete model.
        # An empty key is sent as the conventional "EMPTY" placeholder
        # because the OpenAI client rejects empty credentials outright,
        # even on endpoints (e.g. Ollama) that ignore them.
        self._client = init_chat_model(
            model=model,
            model_provider=self.provider,
            api_key=self.api_key or SecretStr("EMPTY"),
            base_url=base_url,
            **kwargs,
        )

    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Generate a completion for the given chat ``messages``.

        :param messages: Chat history as a list of ``{"role": ..., "content": ...}`` message dicts.
        :return: The model's text completion.
        :raises RuntimeError: If the backend fails to produce a response.
        """
        try:
            response = self._client.invoke(messages)
        except Exception as exc:
            raise RuntimeError(f"Completion failed: {exc}") from exc
        content = response.content
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        return str(content)

    def bind_capabilities(self, caps: list[Any]) -> ModelProvider:
        """Bind capabilities to the model provider.

        :param caps: List of capabilities to bind.
        :return: The provider with bound capabilities.
        """
        # tool-binding is handled by the LangGraph layer; no-op here.
        return self
