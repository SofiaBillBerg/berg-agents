"""Berg Agents chat-server protocol.

Framework-agnostic contract that every chat surface (FastAPI web, TUI loop,
future native backend) implements.  The point is that `berg_agents/ui/web.py`
becomes a thin FastAPI adapter over a concrete `ChatServer` instead of being
the source of truth.

Design rules:

* No FastAPI, LangGraph, or web framework imports here.
* Streaming returns an iterator of protocol events (SSE-shape), so any
  transport (SSE, WebSocket, in-process queue) can use it.
* Pydantic models live in `berg_agents.core.chat_schema` so the protocol
  file stays small.  The web adapter re-uses those models for its
  request/response bodies.
* Methods that today return `StreamingResponse` (SSE) return
  `Iterable[ProtocolEvent]` here; the adapter adds the `data: ` prefix and
  the event-id header.
* Legacy `/chat/*` routes (the "current chat" pointer) are preserved as
  thin convenience methods that delegate to a thread-based implementation
  using the active thread id.
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

    `data` is the protocol-shaped payload (already JSON-serialisable).
    `id` is the seq number from the protocol v2 envelope; the adapter
    uses it as the SSE `id:` field for resumable streams.
    `event` is the protocol v2 method (e.g. "messages", "tools", "lifecycle").
    """

    __slots__ = ("data", "event", "id", "namespace", "node")

    def __init__(
        self,
        *,
        id: int,
        event: str,
        data: Any,
        namespace: tuple[str, ...] = (),
        node: str | None = None,
    ) -> None:
        self.id = id
        self.event = event
        self.data = data
        self.namespace = namespace
        self.node = node

    def to_dict(self) -> dict[str, Any]:
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
        self.thread_id = thread_id
        self.created_at = created_at
        self.updated_at = updated_at
        self.metadata = dict(metadata)
        self.values = dict(values)

    def to_dict(self) -> dict[str, Any]:
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
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.display_name = display_name
        self.is_active = is_active

    def to_dict(self) -> dict[str, Any]:
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
        self.name = name
        self.model = model
        self.is_active = is_active
        self.base_url = base_url
        self.api_key_set = api_key_set

    def to_dict(self) -> dict[str, Any]:
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
    `ProtocolEvent`; callers may iterate once and stop on cancel.
    """

    # ----- Provider / model metadata ---------------------------------

    def list_providers(self) -> list[ProviderConfig]: ...
    def get_active_provider(self) -> ProviderConfig: ...
    def set_active_provider(self, name: str, model: str) -> ProviderConfig: ...

    def list_models(self) -> list[ModelInfo]: ...
    def list_capabilities(self) -> list[dict[str, Any]]: ...

    # ----- Threads ----------------------------------------------------

    def create_thread(
        self,
        thread_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        if_exists: str | None = None,
    ) -> ThreadInfo: ...

    def get_thread_state(self, thread_id: str) -> dict[str, Any]: ...
    def get_thread_history(self, thread_id: str) -> list[dict[str, Any]]: ...

    def set_thread_model(
        self,
        thread_id: str,
        provider: str,
        model: str,
        base_url: str | None = None,
    ) -> dict[str, Any]: ...

    def export_thread(self, thread_id: str, format: str = "md") -> str: ...

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

    def cancel_run(self, thread_id: str, run_id: str) -> dict[str, Any]: ...

    def respond_interrupt(
        self,
        thread_id: str,
        response: Any,
        interrupt_id: str | None = None,
    ) -> dict[str, Any]: ...

    def thread_stream_events(
        self,
        thread_id: str,
        since: int = 0,
    ) -> Iterable[ProtocolEvent]:
        """Full thread event stream (replay-from-`since` or live tail)."""
        ...

    # ----- Legacy "current chat" pointer convenience methods -----------
    #
    # These exist so the old /chat/* routes keep working.  They delegate
    # to an implementation that picks an "active" thread (e.g. a session
    # in a TUI or the most-recently-touched thread in a web session).

    def chat(self, text: str) -> dict[str, Any]: ...
    def chat_stream(self, text: str) -> Iterable[ProtocolEvent]: ...
    def chat_resume(self, response: Any) -> dict[str, Any]: ...
    def chat_cancel(self) -> dict[str, Any]: ...
    def chat_history(self) -> list[dict[str, Any]]: ...
    def chat_audit(self, action: str = "read") -> dict[str, Any]: ...

    # ----- Capabilities (audited invocation) --------------------------

    def invoke_capability(
        self,
        capability_id: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]: ...


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
    def list_providers(self) -> list[ProviderConfig]: ...
    @abstractmethod
    def get_active_provider(self) -> ProviderConfig: ...
    @abstractmethod
    def set_active_provider(self, name: str, model: str) -> ProviderConfig: ...

    @abstractmethod
    def list_models(self) -> list[ModelInfo]: ...
    @abstractmethod
    def list_capabilities(self) -> list[dict[str, Any]]: ...

    # --- threads ---

    @abstractmethod
    def create_thread(
        self,
        thread_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        if_exists: str | None = None,
    ) -> ThreadInfo: ...
    @abstractmethod
    def get_thread_state(self, thread_id: str) -> dict[str, Any]: ...
    @abstractmethod
    def get_thread_history(self, thread_id: str) -> list[dict[str, Any]]: ...
    @abstractmethod
    def set_thread_model(
        self,
        thread_id: str,
        provider: str,
        model: str,
        base_url: str | None = None,
    ) -> dict[str, Any]: ...
    @abstractmethod
    def export_thread(self, thread_id: str, format: str = "md") -> str: ...

    # --- runs ---

    @abstractmethod
    def start_run(
        self,
        thread_id: str,
        input_messages: list[dict[str, Any]],
    ) -> dict[str, Any]: ...
    @abstractmethod
    def stream_run(
        self,
        thread_id: str,
        run_id: str,
        since: int = 0,
    ) -> Iterable[ProtocolEvent]: ...
    @abstractmethod
    def cancel_run(self, thread_id: str, run_id: str) -> dict[str, Any]: ...
    @abstractmethod
    def respond_interrupt(
        self,
        thread_id: str,
        response: Any,
        interrupt_id: str | None = None,
    ) -> dict[str, Any]: ...
    @abstractmethod
    def thread_stream_events(
        self,
        thread_id: str,
        since: int = 0,
    ) -> Iterable[ProtocolEvent]: ...

    # --- legacy chat ---

    @abstractmethod
    def chat(self, text: str) -> dict[str, Any]: ...
    @abstractmethod
    def chat_stream(self, text: str) -> Iterable[ProtocolEvent]: ...
    @abstractmethod
    def chat_resume(self, response: Any) -> dict[str, Any]: ...
    @abstractmethod
    def chat_cancel(self) -> dict[str, Any]: ...
    @abstractmethod
    def chat_history(self) -> list[dict[str, Any]]: ...
    @abstractmethod
    def chat_audit(self, action: str = "read") -> dict[str, Any]: ...

    # --- capabilities ---

    @abstractmethod
    def invoke_capability(
        self,
        capability_id: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]: ...


__all__ = [
    "ChatServer",
    "ChatServerBase",
    "ModelInfo",
    "ProtocolEvent",
    "ProviderConfig",
    "ThreadInfo",
]
