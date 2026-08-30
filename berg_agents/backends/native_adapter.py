"""Native adapter for berg_agents — raw LLM calls without LangChain.

This module provides a framework-free backend that talks directly to
OpenAI-compatible endpoints (Ollama, vLLM, LM Studio, Omniroute, etc.)
using plain HTTP. It has ZERO LangChain/LangGraph dependencies.

It is the default backend when LangChain is not installed.
"""

from __future__ import annotations

import json
import logging
from typing import Any
import urllib.error
import urllib.request

from berg_agents.core.interface import AbstractAgent, AgentResult, TaskContext

logger = logging.getLogger(__name__)


class NativeAdapter:
    """Adapter that calls an OpenAI-compatible API directly.

    Uses only stdlib (urllib) — no external dependencies.

    Usage:
        adapter = NativeAdapter(base_url="http://localhost:11434/v1", model="qwen3.5:9b")
        response = adapter.chat([{"role": "user", "content": "hello"}])
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen3.5:9b",
        api_key: str = "EMPTY",
        timeout: int = 60,
    ) -> None:
        """Initialize the native adapter.

        Args:
            base_url: OpenAI-compatible endpoint (e.g. Ollama http://localhost:11434/v1).
            model: Model identifier.
            api_key: API key (ignored by Ollama, required by OpenAI).
            timeout: Request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Send a chat completion request.

        Args:
            messages: List of {"role": str, "content": str} dicts.
            tools: Optional OpenAI tool definitions.
            temperature: Sampling temperature.

        Returns:
            Parsed JSON response dict.

        Raises:
            RuntimeError: On HTTP or API errors.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM API error {e.code}: {body_text}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"LLM connection failed: {e.reason}") from e

    def complete(self, prompt: str, system: str | None = None) -> str:
        """Simple completion helper.

        Args:
            prompt: User prompt.
            system: Optional system prompt.

        Returns:
            Assistant text content.
        """
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = self.chat(messages)
        choices = resp.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None = None) -> NativeAdapter:
        """Create adapter from bergagents.jsonc config.

        Args:
            cfg: Optional config dict (defaults to app settings).

        Returns:
            Configured NativeAdapter instance.
        """
        if cfg is None:
            from berg_agents.config.settings import get_settings

            cfg = get_settings().model_dump()

        # Use the provider registry to resolve the default model
        try:
            from berg_agents.providers.registry import resolve_model

            resolved = resolve_model(cfg.get("default_model") or None, cfg)
            return cls(
                base_url=resolved.get("base_url", "http://localhost:11434/v1"),
                model=resolved.get("model", "qwen3.5:9b"),
                api_key=resolved.get("api_key", "EMPTY"),
            )
        except (KeyError, ImportError):
            return cls()


class NativeAgent(AbstractAgent):
    """A native agent backed by direct LLM API calls.

    Implements AbstractAgent using NativeAdapter for execution.
    No LangChain dependency.
    """

    def __init__(
        self,
        name: str = "native",
        adapter: NativeAdapter | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """Initialize the native agent.

        Args:
            name: Agent name.
            adapter: LLM adapter (created from config if not provided).
            system_prompt: Optional system prompt for the agent.
        """
        self.name = name
        self.description = f"Native agent: {name} (no framework)"
        self.preferred_model_tier = "small"
        self.capabilities = ["native", "direct_llm", "no_framework"]
        self._adapter = adapter
        self._system_prompt = system_prompt or "You are a helpful assistant."

    def _get_adapter(self) -> NativeAdapter:
        """Get or create the LLM adapter."""
        if self._adapter is None:
            self._adapter = NativeAdapter.from_config()
        return self._adapter

    def can_handle(self, task: dict[str, Any]) -> float:
        """Native agent can handle any task with a description.

        Args:
            task: Task dictionary.

        Returns:
            Confidence score (0.6 — native is less capable than LangGraph).
        """
        if "description" in task:
            return 0.6
        return 0.1

    def execute(
        self,
        task: dict[str, Any],
        context: TaskContext,
        model: Any = None,
    ) -> AgentResult:
        """Execute the task via direct LLM call.

        Args:
            task: Task dictionary with at least 'description'.
            context: Task context with complexity and risk info.
            model: Unused (native uses its own adapter).

        Returns:
            AgentResult with LLM response.
        """
        try:
            adapter = self._get_adapter()
            result = adapter.complete(
                prompt=context.description,
                system=self._system_prompt,
            )
            return AgentResult(
                success=True,
                output=result,
                model_used=adapter.model,
            )
        except Exception as e:
            logger.warning("Native agent execution failed: %s", e)
            return AgentResult(
                success=False,
                error=str(e),
            )
