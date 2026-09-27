"""Berg Agents chat-server protocol.

Framework-agnostic contract that every chat surface (FastAPI web, TUI loop,
future backend) implements.  The point is that `berg_agents/ui/web.py`
becomes a thin FastAPI adapter over a concrete `ChatServer` instead of being
the source of truth.

Design rules:

* Streaming returns an iterator of protocol events (SSE-shape), so any
  transport (SSE, WebSocket, in-process queue) can use it.
* Pydantic models live in `berg_agents.core.chat_schema` so the protocol
  file stays small.  The web adapter re-uses those models for its
  request/response bodies.
* Methods that today return `StreamingResponse` (SSE) return
  `Iterable[ProtocolEvent]` here; the adapter adds the `data: ` prefix and
  the event-id header.
* Thread-based runs are the only execution surface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Event types (wire-shape, SSE-compatible)
# ---------------------------------------------------------------------------


class ProtocolEvent:
    """A single line in the SSE stream.

    `data` is the protocol-shaped payload (already JSON-serializable).
    `id` is the seq number from the protocol v2 envelope; the adapter
    uses it as the SSE `id:` field for resumable streams.
    `event` is the protocol v2 method (e.g. "messages", "tools", "lifecycle").
    """

    __slots__ = ("data", "event", "id", "namespace", "node")

    def __init__(
        self,
        *,
        id: int,  # ruff: ignore[builtin-argument-shadowing]
        event: str,
        data: Any,
        namespace: tuple[str, ...] = (),
        node: str | None = None,
    ) -> None:
        """Initialize protocol event."""
        self.id = id
        self.event = event
        self.data = data
        self.namespace = namespace
        self.node = node

    def to_dict(self) -> dict[str, Any]:
        """Access protocol event."""
        out: dict[str, Any] = {
            "seq": self.id,
            "method": self.event,
            "params": {
                "namespace": list(self.namespace),
                "data": self.data,
            },
        }
        if self.node is not None:
            out["params"]["node"] = self.node
        return out


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class ThreadInfo:
    """A thread as returned by create_thread / thread_state."""

    __slots__ = ("created_at", "metadata", "thread_id", "updated_at", "values")

    def __init__(
        self,
        thread_id: str,
        created_at: str,
        updated_at: str,
        metadata: Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> None:
        """Initialize thread info."""
        self.thread_id = thread_id
        self.created_at = created_at
        self.updated_at = updated_at
        self.metadata = dict(metadata)
        self.values = dict(values)

    def to_dict(self) -> dict[str, Any]:
        """Access thread info."""
        return {
            "thread_id": self.thread_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "values": self.values,
        }


class ModelInfo:
    """A model as returned by list_models."""

    __slots__ = ("base_url", "display_name", "is_active", "model", "provider")

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        base_url: str | None,
        display_name: str,
        is_active: bool = False,
    ) -> None:
        """A provider entry as returned by list_providers."""
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.display_name = display_name
        self.is_active = is_active

    def to_dict(self) -> dict[str, Any]:
        """A protocol for a chat server.

        :return: The provider configuration as a dictionary.
        """
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "display_name": self.display_name,
            "is_active": self.is_active,
        }


class ProviderConfig:
    """A provider entry as returned by list_providers."""

    __slots__ = ("api_key_set", "base_url", "is_active", "model", "name")

    def __init__(
        self,
        *,
        name: str,
        model: str,
        is_active: bool,
        base_url: str | None = None,
        api_key_set: bool = False,
    ) -> None:
        """Initialize provider config."""
        self.name = name
        self.model = model
        self.is_active = is_active
        self.base_url = base_url
        self.api_key_set = api_key_set

    def to_dict(self) -> dict[str, Any]:
        """Set the active provider."""
        return {
            "name": self.name,
            "model": self.model,
            "is_active": self.is_active,
            "base_url": self.base_url,
            "api_key_set": self.api_key_set,
        }


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ChatServer(Protocol):
    """Framework-agnostic chat server surface.

    The current FastAPI handlers in `berg_agents.ui.web` are a single
    implementation.  A TUI loop and a future LangGraph-free backend will
    be other implementations.  Methods that stream return an iterable of
    `ProtocolEvent`;     callers may iterate once and stop on cancel.
    """

    # ----- Provider / model metadata ---------------------------------

    def list_providers(self) -> list[ProviderConfig]:
        """List all available providers.

        :return: A list of provider configurations.
        :rtype: list[ProviderConfig]
        """
        ...

    def get_active_provider(self) -> ProviderConfig:
        """Get the currently active provider.

        :return: The active provider configuration.
        :rtype: ProviderConfig
        """
        ...

    def set_active_provider(self, name: str, model: str) -> ProviderConfig:
        """Set the active provider.

        :param name:
        :type name:
        :param model:
        :type model:
        """
        ...

    def list_models(self) -> list[ModelInfo]:
        """List all available models.

        :return: A list of model information.
        :rtype: list[ModelInfo]
        """
        ...

    def list_capabilities(self) -> list[dict[str, Any]]:
        """List all available capabilities.

        :return: A list of capability dictionaries.
        :rtype: list[dict[str, Any]]
        """
        ...

    # ----- Threads ----------------------------------------------------

    def create_thread(
        self,
        thread_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        if_exists: str | None = None,
    ) -> ThreadInfo:
        """Create a thread.

        :param thread_id:
        :type thread_id:
        :param metadata:
        :type metadata:
        :param if_exists:
        :type if_exists:
        """
        ...

    def get_thread_state(self, thread_id: str) -> dict[str, Any]:
        """Get current thread state.

        :param thread_id:
        :type thread_id:
        """
        ...

    def get_thread_history(self, thread_id: str) -> list[dict[str, Any]]:
        """Get thread history.

        :param thread_id:
        :type thread_id:
        """
        ...

    def set_thread_model(
        self,
        thread_id: str,
        provider: str,
        model: str,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Set the model for a thread.

        :param thread_id:
        :type thread_id:
        :param provider:
        :type provider:
        :param model:
        :type model:
        :param base_url:
        :type base_url:
        """
        ...

    def export_thread(self, thread_id: str, format: str = "md") -> str:  # ruff: ignore[builtin-argument-shadowing]
        """Export current conversation by thread.

        :param thread_id:
        :type thread_id:
        :param format:
        :type format:
        """
        ...

    # ----- Runs / streaming -------------------------------------------

    def start_run(
        self,
        thread_id: str,
        input_messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Begin a new run. Returns ``{"run_id": str, "thread_id": str}``."""
        ...

    def stream_run(
        self,
        thread_id: str,
        run_id: str,
        since: int = 0,
    ) -> Iterable[ProtocolEvent]:
        """Server-Sent Events for one run. Replay from `since` if given."""
        ...

    def cancel_run(self, thread_id: str, run_id: str) -> dict[str, Any]:
        """
        Cancel a run.

        :param thread_id:
        :type thread_id:
        :param run_id:
        :type run_id:
        """
        ...

    def respond_interrupt(
        self,
        thread_id: str,
        response: Any,
        interrupt_id: str | None = None,
    ) -> dict[str, Any]:
        """Respond to an interrupt.

        :param thread_id:
        :type thread_id:
        :param response:
        :type response:
        :param interrupt_id:
        :type interrupt_id:
        """
        ...

    def thread_stream_events(
        self,
        thread_id: str,
        since: int = 0,
    ) -> Iterable[ProtocolEvent]:
        """Full thread event stream (replay-from-`since` or live tail)."""
        ...

    # ----- Capabilities (audited invocation) --------------------------

    def invoke_capability(
        self,
        capability_id: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """
        Invoke a capability with the given parameters.

        :param capability_id: The ID of the capability to invoke.
        :type capability_id: str
        :param params: The parameters to pass to the capability.
        :type params: Mapping[str, Any]
        """
        ...


# ---------------------------------------------------------------------------
# Abstract base (optional convenience for implementers)
# ---------------------------------------------------------------------------


class ChatServerBase(ABC):
    """Convenience ABC for ChatServer implementations.

    Subclasses still have to implement every abstract method; this just
    gives them a clear placeholder to override and makes it easy to add
    shared helpers (metrics, logging, capability injection) later.
    """

    # --- providers ---

    @abstractmethod
    def list_providers(self) -> list[ProviderConfig]:
        """List all available providers."""
        ...

    @abstractmethod
    def get_active_provider(self) -> ProviderConfig:
        """Get active provider."""
        ...

    @abstractmethod
    def set_active_provider(self, name: str, model: str) -> ProviderConfig:
        """Set active provider."""
        ...

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        """List all available models."""
        ...

    @abstractmethod
    def list_capabilities(self) -> list[dict[str, Any]]:
        """List all available capabilities.

        :return: A list of available capabilities.
        :rtype: list[dict[str, Any]]
        """
        ...

    # --- threads ---

    @abstractmethod
    def create_thread(
        self,
        thread_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        if_exists: str | None = None,
    ) -> ThreadInfo:
        """Create a new thread.

        :param thread_id: The ID of the thread to create.
        :type thread_id: str | None
        :param metadata: The metadata to associate with the thread.
        :type metadata: Mapping[str, Any] | None
        :param if_exists: What to do if the thread already exists.
        :type if_exists: str | None
        """
        ...

    @abstractmethod
    def get_thread_state(self, thread_id: str) -> dict[str, Any]:
        """Get the state of a specific thread.

        :param thread_id: The ID of the thread to get the state for.
        :type thread_id: str
        """
        ...

    @abstractmethod
    def get_thread_history(self, thread_id: str) -> list[dict[str, Any]]:
        """Get the history of a specific thread.

        :param thread_id: The ID of the thread to get the history for.
        :type thread_id: str
        """
        ...

    @abstractmethod
    def set_thread_model(
        self,
        thread_id: str,
        provider: str,
        model: str,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Set the model for a specific thread.

        :param thread_id:
        :param provider:
        :param model:
        :param base_url:
        """
        ...

    @abstractmethod
    def export_thread(self, thread_id: str, format: str = "md") -> str:  # ruff: ignore[builtin-argument-shadowing]
        """Export a thread in a specific format.

        :param thread_id:
        :type thread_id:
        :param format:
        :type format:
        """
        ...

    # --- runs ---

    @abstractmethod
    def start_run(
        self,
        thread_id: str,
        input_messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Start a new run.

        :param thread_id: The ID of the thread to start the run in.
        :type thread_id: str
        :param input_messages: The messages to use as input for the run.
        :type input_messages: list[dict[str, Any]]
        """
        ...

    @abstractmethod
    def stream_run(
        self,
        thread_id: str,
        run_id: str,
        since: int = 0,
    ) -> Iterable[ProtocolEvent]:
        """Stream the events for a specific run.

        :param thread_id: The ID of the thread to stream events for.
        :type thread_id: str
        :param run_id: The ID of the run to stream events for.
        :type run_id: str
        :param since: The timestamp to start streaming from.
        :type since: int
        """
        ...

    @abstractmethod
    def cancel_run(self, thread_id: str, run_id: str) -> dict[str, Any]:
        """Cancel running task.

        :param thread_id:
        :type thread_id:
        :param run_id:
        :type run_id:
        """
        ...

    @abstractmethod
    def respond_interrupt(
        self,
        thread_id: str,
        response: Any,
        interrupt_id: str | None = None,
    ) -> dict[str, Any]:
        """Respond to an interrupt.

        :param thread_id:
        :type thread_id:
        :param response:
        :type response:
        :param interrupt_id:
        :type interrupt_id:
        """
        ...

    @abstractmethod
    def thread_stream_events(
        self,
        thread_id: str,
        since: int = 0,
    ) -> Iterable[ProtocolEvent]:
        """Stream events for a specific thread.

        :param thread_id: The ID of the thread to stream events for.
        :type thread_id: str
        :param since: The timestamp to start streaming from.
        :type since: int
        """
        ...

    # --- capabilities ---

    @abstractmethod
    def invoke_capability(
        self,
        capability_id: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Invoke a capability.

        :param capability_id:
        :type capability_id:
        :param params:
        :type params:
        """
        ...


__all__ = [
    "ChatServer",
    "ChatServerBase",
    "ModelInfo",
    "ProtocolEvent",
    "ProviderConfig",
    "ThreadInfo",
]
