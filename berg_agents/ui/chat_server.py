"""Pure Python Chat Server and Event Orchestrator for the Berg Agents Web UI.

This module provides the core state, thread management, and event-dispatching
logic for the FastAPI backend, completely free from any LangChain, LangGraph,
or DeepAgents dependencies. It communicates with configured LLM providers,
dispatches capability invocations, and streams structured SSE events to the
Next.js React frontend.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from berg_agents.capabilities.registry import CapabilityRegistry
from berg_agents.config.settings import get_settings
from berg_agents.main import load_config
from berg_agents.providers.registry import (
    build_llm,
    list_models as registry_list_models,
    resolve_model,
)
from berg_agents.ui.protocol import _sse

logger = logging.getLogger(__name__)


class ChatServer:
    """Thread-safe, pure Python server managing web chat sessions and events.

    Attributes:
        _threads: Mapping of thread_id -> thread metadata and message records.
        _protocol_event_queues: In-memory sequence queues for protocol events.
        _protocol_stream_notifiers: Asyncio event triggers for SSE listeners.
        _pending_hitl: Threads paused awaiting human-in-the-loop decisions.
        _switching: Flag indicating if a provider switch is currently underway.
        _active_provider: Currently selected provider name.
        _active_model: Currently selected model identifier.
    """

    def __init__(self) -> None:
        """Initialize the ChatServer instance with empty in-memory state."""
        self._threads: dict[str, dict[str, Any]] = {}
        self._thread_agents: dict[str, Any] = {}
        self._protocol_event_queues: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        self._protocol_stream_notifiers: dict[str, asyncio.Event] = {}
        self._pending_hitl: dict[str, asyncio.Event] = {}
        self._pending_interrupt_ids: dict[str, str] = {}
        self._hitl_payloads: dict[str, Any] = {}
        self._active_runs: dict[str, asyncio.Task[Any]] = {}
        self._llm_cache: dict[tuple[str, str, str | None], Any] = {}
        self._audit_store: list[dict[str, Any]] = []
        self._switching = False
        self._provider_switch_lock = asyncio.Lock()
        self._registry: CapabilityRegistry | None = None

        settings = get_settings()
        self._active_provider = settings.provider or "ollama"
        self._active_model = (
            settings.ollama_model
            if self._active_provider == "ollama"
            else settings.openai_model or "gpt-oss:20b"
        )

    # -----------------------------------------------------------------------
    # Provider & Model Management
    # -----------------------------------------------------------------------

    def list_providers(self) -> list[dict[str, Any]]:
        """Return all configured providers and models from application settings."""
        settings = get_settings()
        raw_list = settings.provider_list or []
        if not raw_list:
            return [
                {"name": "ollama", "model": settings.ollama_model or "qwen3.5:9b"},
                {"name": "openai", "model": settings.openai_model or "gpt-4o"},
            ]
        return [{"name": p["name"], "model": p["model"]} for p in raw_list]

    def get_active_provider(self) -> dict[str, Any]:
        """Return the currently active LLM provider and model."""
        return {
            "provider": self._active_provider,
            "model": self._active_model,
        }

    def validate_provider(
        self, provider: str, model: str
    ) -> str | None:
        """Validate provider and model combination against declared list."""
        settings = get_settings()
        configured = settings.provider_list or []
        if configured:
            valid = {(p["name"], p["model"]) for p in configured}
            if (provider, model) not in valid:
                return (
                    f"Provider {provider!r} / model {model!r} is not in the "
                    f"configured provider_list: {sorted(valid)}"
                )
        return None

    async def set_active_provider(
        self, provider: str, model: str
    ) -> dict[str, str]:
        """Switch active provider and model dynamically."""
        if self._switching:
            return {"status": "error", "detail": "Switch already in progress"}

        async with self._provider_switch_lock:
            self._switching = True
            try:
                self._active_provider = provider
                self._active_model = model
                return {"status": "ok"}
            finally:
                self._switching = False

    def is_switching(self) -> bool:
        """Return True if a provider switch operation is currently running."""
        return self._switching

    def list_models(self) -> list[dict[str, Any]]:
        """Return available models for UI dynamic selectors with active status."""
        cfg = load_config()
        models = registry_list_models(cfg)
        try:
            default = resolve_model(cfg.get("default_model") or None, cfg)
            default_id = default["model"]
        except Exception:
            default_id = self._active_model

        for entry in models:
            entry["is_active"] = entry["model"] == default_id or (
                entry.get("provider") == self._active_provider
                and entry.get("model") == self._active_model
            )
        return models

    def _get_llm_for_thread(self, thread: dict[str, Any]) -> Any:
        """Return a cached chat model instance for the thread's provider/model."""
        cfg = load_config()
        provider = thread.get("provider") or self._active_provider
        model_id = thread.get("model") or self._active_model
        base_url = thread.get("base_url")
        cache_key = (provider, model_id, base_url)

        llm = self._llm_cache.get(cache_key)
        if llm is not None:
            return llm

        resolved = resolve_model(model_id, cfg)
        if base_url:
            resolved["base_url"] = base_url

        llm = build_llm(resolved)
        self._llm_cache[cache_key] = llm
        return llm

    @staticmethod
    def _normalize_completion_text(response: Any) -> str:
        """Convert a chat model response into a plain text string."""
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "\n".join(str(part) for part in content)
        return str(content or "").strip()

    @staticmethod
    def _stream_chunks(text: str) -> list[str]:
        """Split text into whitespace-preserving chunks for SSE streaming."""
        chunks = [part for part in re.split(r"(\s+)", text) if part]
        return chunks or ([text] if text else [])

    def _complete_thread_text(self, thread_id: str) -> str:
        """Invoke the configured model for the thread and return its text."""
        thread = self._threads.get(thread_id)
        if thread is None:
            raise ValueError(f"Thread {thread_id} not found")

        llm = self._get_llm_for_thread(thread)
        response = llm.invoke(thread.get("messages", []))
        return self._normalize_completion_text(response)

    # -----------------------------------------------------------------------
    # Capability Layer Access
    # -----------------------------------------------------------------------

    def _get_registry(self) -> CapabilityRegistry:
        """Return the shared capability registry, building lazily if needed."""
        if self._registry is None:
            from berg_agents.cli import _build_registry

            self._registry = _build_registry()
        return self._registry

    def list_capabilities(self) -> list[dict[str, Any]]:
        """Return discovery metadata for every registered capability."""
        return self._get_registry().discover()

    def invoke_capability(
        self, capability_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Dispatch a capability invocation directly and return result with audit."""
        from berg_agents.capabilities.envelope import InvocationRequest

        request = InvocationRequest(
            request_id=uuid.uuid4().hex,
            capability_id=capability_id,
            params=params,
            caller="web",
        )
        response, receipt = self._get_registry().dispatch(request)
        if response.status == "error":
            raise ValueError(response.error or f"Capability {capability_id} execution failed")
        return {
            "response": response.model_dump(),
            "receipt": receipt.model_dump(),
        }

    # -----------------------------------------------------------------------
    # Thread & State Management
    # -----------------------------------------------------------------------

    def create_thread(
        self,
        thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        if_exists: str | None = None,
    ) -> dict[str, Any]:
        """Create and store a new thread conversation record."""
        tid = thread_id or uuid.uuid4().hex
        if tid in self._threads and if_exists == "raise":
            raise ValueError(f"Thread {tid} already exists")

        now = datetime.datetime.now(datetime.UTC).isoformat()
        record = {
            "thread_id": tid,
            "created_at": now,
            "updated_at": now,
            "metadata": metadata or {},
            "messages": [],
            "values": {},
            "provider": self._active_provider,
            "model": self._active_model,
        }
        self._threads[tid] = record
        return record

    async def get_thread_state(self, thread_id: str) -> dict[str, Any]:
        """Return the current conversational state and message history for a thread."""
        thread = self._threads.get(thread_id)
        if not thread:
            return {"values": {}, "messages": [], "next": [], "tasks": []}

        return {
            "values": thread.get("values", {}),
            "messages": thread.get("messages", []),
            "next": [],
            "tasks": [],
        }

    async def get_thread_history(self, thread_id: str) -> list[dict[str, Any]]:
        """Return historical snapshots for a given thread."""
        state = await self.get_thread_state(thread_id)
        return [state] if state.get("messages") else []

    async def set_thread_model(
        self,
        thread_id: str,
        provider: str,
        model: str,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Associate a specific model configuration with a given thread."""
        thread = self._threads.get(thread_id)
        if not thread:
            self.create_thread(thread_id)
            thread = self._threads[thread_id]

        thread["provider"] = provider
        thread["model"] = model
        if base_url:
            thread["base_url"] = base_url

        return {
            "status": "ok",
            "thread_id": thread_id,
            "provider": provider,
            "model": model,
        }

    async def export_thread(self, thread_id: str, format: str = "md") -> str:
        """Export conversation messages as formatted Markdown text."""
        thread = self._threads.get(thread_id)
        if not thread:
            raise ValueError(f"Thread {thread_id} not found")

        messages = thread.get("messages", [])
        lines = [
            f"# Berg Agents Chat Transcript — Thread `{thread_id}`",
            f"*Generated: {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}*",
            f"*Model: {thread.get('provider')}:{thread.get('model')}*",
            "",
            "---",
            "",
        ]

        for msg in messages:
            role = msg.get("role", "assistant").upper()
            content = msg.get("content") or msg.get("text") or ""
            lines.append(f"### {role}")
            lines.append(content)
            lines.append("")

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Protocol Events & Streaming
    # -----------------------------------------------------------------------

    def _get_or_create_queue(
        self, thread_id: str
    ) -> list[tuple[int, dict[str, Any]]]:
        """Get or initialize the sequential protocol event queue for a thread."""
        if thread_id not in self._protocol_event_queues:
            self._protocol_event_queues[thread_id] = []
        return self._protocol_event_queues[thread_id]

    def _get_or_create_notifier(self, thread_id: str) -> asyncio.Event:
        """Get or initialize the event trigger for SSE event subscribers."""
        if thread_id not in self._protocol_stream_notifiers:
            self._protocol_stream_notifiers[thread_id] = asyncio.Event()
        return self._protocol_stream_notifiers[thread_id]

    def _push_protocol_event(
        self, thread_id: str, event: dict[str, Any]
    ) -> None:
        """Enqueue an event with a monotonically increasing sequence id and notify."""
        queue = self._get_or_create_queue(thread_id)
        notifier = self._get_or_create_notifier(thread_id)
        seq = len(queue) + 1
        queue.append((seq, event))

        if event.get("method") == "input":
            params = event.get("params", {})
            data = params.get("data", {})
            if data.get("event") == "input-requested":
                interrupt_id = data.get("id")
                if interrupt_id:
                    self._pending_interrupt_ids[thread_id] = interrupt_id
                self._hitl_payloads[thread_id] = data.get("value")

        notifier.set()

    async def stream_protocol_events(
        self, thread_id: str, since: int = 0
    ) -> AsyncGenerator[tuple[int, dict[str, Any]], None]:
        """Yield protocol events as they arrive on the thread queue."""
        queue = self._get_or_create_queue(thread_id)
        notifier = self._get_or_create_notifier(thread_id)
        cursor = since

        while True:
            # Replay any backlog items beyond cursor
            while cursor < len(queue):
                seq, event = queue[cursor]
                cursor += 1
                yield seq, event

            notifier.clear()
            try:
                # Wait for next event notification with a periodic heartbeat timeout
                await asyncio.wait_for(notifier.wait(), timeout=15.0)
            except asyncio.TimeoutError:
                # Send periodic heartbeat ping
                yield 0, {"method": "heartbeat", "params": {"timestamp": datetime.datetime.now(datetime.UTC).isoformat()}}

    async def thread_stream_events(
        self, thread_id: str, since: int = 0
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield event dicts formatted for the SSE protocol."""
        async for seq, event in self.stream_protocol_events(thread_id, since):
            yield event

    # -----------------------------------------------------------------------
    # Protocol Commands & Run Execution
    # -----------------------------------------------------------------------

    async def handle_protocol_command(
        self,
        thread_id: str,
        method: str,
        params: dict[str, Any],
        command_id: int | str = 0,
    ) -> dict[str, Any]:
        """Dispatch frontend protocol commands (run.start, interrupt.respond, etc)."""
        if method == "run.start":
            input_data = params.get("input", {})
            messages = input_data.get("messages", [])
            user_text = ""
            for msg in messages:
                if msg.get("role") in {"user", "human"}:
                    user_text = msg.get("content", "")

            # Ensure thread exists
            if thread_id not in self._threads:
                self.create_thread(thread_id)

            thread = self._threads[thread_id]
            thread["messages"].append({"role": "user", "content": user_text})

            # Spawn async run task
            task = asyncio.create_task(self._execute_chat_run(thread_id, user_text))
            self._active_runs[thread_id] = task

            return {"status": "started", "thread_id": thread_id}

        if method == "interrupt.respond" or method == "input.respond":
            decision = params.get("decision") or params.get("response") or "approve"
            self.resume_hitl(thread_id, decision)
            return {"status": "resumed", "thread_id": thread_id}

        if method == "run.cancel":
            self.cancel_run(thread_id)
            return {"status": "cancelled", "thread_id": thread_id}

        if method == "thread.get_state":
            state = await self.get_thread_state(thread_id)
            return {"status": "ok", "state": state}

        return {"status": "ok", "method": method}

    async def _execute_chat_run(self, thread_id: str, prompt: str) -> None:
        """Execute a conversational completion run and stream progress events."""
        thread = self._threads.get(thread_id, {})
        provider = thread.get("provider", self._active_provider)
        model = thread.get("model", self._active_model)

        # 1. Emit run start lifecycle event
        self._push_protocol_event(
            thread_id,
            {
                "method": "lifecycle",
                "params": {
                    "namespace": [],
                    "data": {"event": "run-started", "thread_id": thread_id},
                },
            },
        )

        try:
            completion_text = await asyncio.to_thread(
                self._complete_thread_text, thread_id
            )
            if not completion_text:
                raise RuntimeError("Model returned no response text")

            # 2. Emit text delta events from the real model response.
            for index, chunk in enumerate(self._stream_chunks(completion_text)):
                self._push_protocol_event(
                    thread_id,
                    {
                        "method": "messages",
                        "params": {
                            "namespace": [],
                            "data": {
                                "event": "content-block-delta",
                                "index": index,
                                "delta": {
                                    "type": "text-delta",
                                    "text": chunk,
                                },
                            },
                        },
                    },
                )

            # Record assistant response in thread history.
            thread.setdefault("messages", []).append(
                {
                    "role": "assistant",
                    "content": completion_text,
                }
            )

            self._push_protocol_event(
                thread_id,
                {
                    "method": "messages",
                    "params": {
                        "namespace": [],
                        "data": {
                            "event": "message-finish",
                            "message": {
                                "role": "assistant",
                                "content": completion_text,
                            },
                        },
                    },
                },
            )

            # 3. Emit run completed event
            self._push_protocol_event(
                thread_id,
                {
                    "method": "lifecycle",
                    "params": {
                        "namespace": [],
                        "data": {"event": "run-completed", "thread_id": thread_id},
                    },
                },
            )

        except Exception as exc:
            logger.exception("Error during chat run execution: %s", exc)
            self._push_protocol_event(
                thread_id,
                {
                    "method": "lifecycle",
                    "params": {
                        "namespace": [],
                        "data": {
                            "event": "run-error",
                            "error": str(exc),
                            "thread_id": thread_id,
                        },
                    },
                },
            )
        finally:
            self._active_runs.pop(thread_id, None)

    # -----------------------------------------------------------------------
    # Legacy Chat Endpoints & HITL Controls
    # -----------------------------------------------------------------------

    async def chat(self, message: str, thread_id: str | None = None) -> dict[str, Any]:
        """Send a chat message synchronously and return response."""
        tid = thread_id or uuid.uuid4().hex
        if tid not in self._threads:
            self.create_thread(tid)

        thread = self._threads[tid]
        thread.setdefault("messages", []).append({"role": "user", "content": message})

        reply = await asyncio.to_thread(self._complete_thread_text, tid)
        thread["messages"].append({"role": "assistant", "content": reply})

        return {
            "response": reply,
            "thread_id": tid,
            "tool_calls": [],
        }

    async def chat_stream(
        self, message: str, thread_id: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream chat tokens via server-sent events."""
        tid = thread_id or uuid.uuid4().hex
        if tid not in self._threads:
            self.create_thread(tid)

        thread = self._threads[tid]
        thread.setdefault("messages", []).append({"role": "user", "content": message})

        reply = await asyncio.to_thread(self._complete_thread_text, tid)
        for chunk in self._stream_chunks(reply):
            yield _sse({"content": chunk, "done": False})
            await asyncio.sleep(0.02)

        thread["messages"].append({"role": "assistant", "content": reply})
        yield _sse({"content": "", "done": True, "thread_id": tid})

    async def chat_history(
        self, thread_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Return the message history for a given thread."""
        thread = self._threads.get(thread_id, {})
        messages = thread.get("messages", [])
        return messages[-limit:]

    def resume_hitl(self, thread_id: str, decision: Any) -> None:
        """Deliver human approval/rejection decision to paused execution."""
        event = self._pending_hitl.pop(thread_id, None)
        if event:
            event.set()
        logger.info("Delivered HITL decision for thread %s: %s", thread_id, decision)

    def cancel_run(self, thread_id: str) -> None:
        """Cancel an ongoing active run for a thread."""
        task = self._active_runs.pop(thread_id, None)
        if task and not task.done():
            task.cancel()
        logger.info("Cancelled active run for thread %s", thread_id)

    def cancel_legacy(self, thread_id: str | None = None) -> None:
        """Cancel a running agent task (legacy endpoint)."""
        if not thread_id or thread_id not in self._active_runs:
            raise ValueError(f"No running task found for thread {thread_id!r}")
        self.cancel_run(thread_id)

    def audit_entry(
        self,
        thread_id: str,
        action: str,
        details: str = "",
        timestamp: str = "",
        user: str = "",
    ) -> dict[str, Any]:
        """Record an audit log entry for a thread action."""
        entry = {
            "thread_id": thread_id,
            "action": action,
            "details": details,
            "timestamp": timestamp or datetime.datetime.now(datetime.UTC).isoformat(),
            "user": user,
        }
        self._audit_store.append(entry)
        return {"status": "recorded"}

    def audit_list(self, thread_id: str) -> list[dict[str, Any]]:
        """Return recorded audit entries for a thread."""
        return [e for e in self._audit_store if e.get("thread_id") == thread_id]


_server_instance: ChatServer | None = None


def get_server() -> ChatServer:
    """Return the global ChatServer singleton instance."""
    global _server_instance
    if _server_instance is None:
        _server_instance = ChatServer()
    return _server_instance
