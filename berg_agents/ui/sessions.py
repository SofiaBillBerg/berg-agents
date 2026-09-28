"""In-memory session state for the FastAPI layer.

Holds per-thread SSE event queues, background tasks, HITL decisions, and
results. The single :class:`SessionManager` instance lives on
``app.state`` (see :mod:`berg_agents.ui.server`) so routes stay thin and
testable through dependency injection — no module-level singletons.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Coroutine
import logging
from typing import Any
import uuid

logger = logging.getLogger(__name__)

#: Cap per-thread event history so long-lived sessions stay bounded.
_MAX_EVENT_LOG = 1000


class _StreamDone:
    """Sentinel marking the end of a thread's event stream."""


_STREAM_DONE = _StreamDone()


class SessionManager:
    """Per-thread session state for streaming, HITL, and cancellation."""

    def __init__(
        self, *, active_provider: str = "ollama", active_model: str = "",
        root_dir: str = ".",
    ) -> None:
        """Initialize empty session state.

        :param active_provider: Initially selected provider name.
        :param active_model: Initially selected model identifier.
        :param root_dir: Workspace root directory for file tools.
        """
        self._threads: set[str] = set()
        self._queues: dict[str, asyncio.Queue] = {}
        self._logs: dict[str, list[dict[str, Any]]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._hitl: dict[str, dict[str, Any]] = {}
        # Per-thread HITL waiters: set when a decision lands or on cancel.
        self._decisions: dict[str, asyncio.Event] = {}
        self.active_provider = active_provider
        self.active_model = active_model
        self._root_dir = root_dir

    def create_thread(self) -> str:
        """Create a thread and return its id."""
        thread_id = uuid.uuid4().hex
        self._threads.add(thread_id)
        self._queues[thread_id] = asyncio.Queue()
        self._logs[thread_id] = []
        self._decisions[thread_id] = asyncio.Event()
        return thread_id

    def adopt_thread(self, thread_id: str) -> str:
        """Register an externally generated thread id.

        Sync ``POST /api/harness`` results carry a harness-made
        task id; adopting it lets ``/respond`` and the event
        stream work on that id without a prior ``create_thread``.

        :param thread_id: Externally generated thread id.
        :return: The adopted thread id.
        """
        self._threads.add(thread_id)
        self._queues.setdefault(thread_id, asyncio.Queue())
        self._logs.setdefault(thread_id, [])
        self._decisions.setdefault(thread_id, asyncio.Event())
        return thread_id

    def has(self, thread_id: str) -> bool:
        """Check whether a thread id is known.

        :param thread_id: Thread id to look up.
        :return: True when the thread exists.
        """
        return thread_id in self._threads

    def push_event(self, thread_id: str, event: dict[str, Any]) -> None:
        """Append an event to a thread's log and live queue.

        :param thread_id: Target thread id.
        :param event: Event payload (must be JSON-serializable).
        """
        log = self._logs.setdefault(thread_id, [])
        log.append(event)
        # Keep newest; trim oldest when over cap.
        if len(log) > _MAX_EVENT_LOG:
            log[:] = log[-_MAX_EVENT_LOG:]
        queue = self._queues.get(thread_id)
        if queue is not None:
            queue.put_nowait(event)

    def event_log(self, thread_id: str) -> list[dict[str, Any]]:
        """Return a thread's retained event history.

        :param thread_id: Thread id to read.
        :return: List of past events (possibly empty).
        """
        return list(self._logs.get(thread_id, []))

    def finish(self, thread_id: str) -> None:
        """Close a thread's live event stream.

        :param thread_id: Thread id whose SSE stream should end.
        """
        queue = self._queues.get(thread_id)
        if queue is not None:
            queue.put_nowait(_STREAM_DONE)

    def delete(self, thread_id: str) -> None:
        """Fully remove a thread and all its state.

        Clears event queue, logs, results, HITL decisions, and
        cancels any running background task for the thread.

        :param thread_id: Thread id to remove completely.
        """
        self._threads.discard(thread_id)
        self._queues.pop(thread_id, None)
        self._logs.pop(thread_id, None)
        self._results.pop(thread_id, None)
        self._hitl.pop(thread_id, None)
        self._decisions.pop(thread_id, None)
        # Cancel any running background task for this thread
        task = self._tasks.get(thread_id)
        if task and not task.done():
            task.cancel()

    async def events(self, thread_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield live events for a thread until it finishes.

        :param thread_id: Thread id to stream.
        :return: Async iterator of event payloads.
        """
        queue = self._queues[thread_id]
        while True:
            event = await queue.get()
            if event is _STREAM_DONE:
                return
            yield event

    def start_background(
        self, thread_id: str, coro: Coroutine[Any, Any, None]
    ) -> None:
        """Track a background task for a thread.

        :param thread_id: Owning thread id.
        :param coro: Coroutine to run as a task.
        """
        task = asyncio.create_task(coro)
        self._tasks[thread_id] = task
        task.add_done_callback(lambda _done: self._tasks.pop(thread_id, None))

    def cancel(self, thread_id: str) -> bool:
        """Cancel a thread's background task.

        :param thread_id: Thread id to cancel.
        :return: True when a running task was canceled.
        """
        task = self._tasks.get(thread_id)
        if task is None or task.done():
            return False
        task.cancel()
        # Wake any parked waiter so it exits promptly via CancelledError.
        event = self._decisions.get(thread_id)
        if event is not None:
            event.set()
        return True

    def set_result(self, thread_id: str, result: dict[str, Any]) -> None:
        """Store a thread's final result.

        :param thread_id: Thread id.
        :param result: Final execution result.
        """
        self._results[thread_id] = result

    def get_result(self, thread_id: str) -> dict[str, Any] | None:
        """Return a thread's final result, if any.

        :param thread_id: Thread id to read.
        :return: Result dict or None.
        """
        return self._results.get(thread_id)

    def set_hitl_decision(
        self,
        thread_id: str,
        decision: str,
        edited_action: dict[str, Any] | None = None,
    ) -> None:
        """Record a human decision for a thread awaiting review.

        :param thread_id: Thread id.
        :param decision: ``"approve"``, ``"edit"``, or ``"reject"``.
        :param edited_action: Reviewer-edited action arguments
            forwarded on resume when the decision is ``"edit"``.
        """
        self._hitl[thread_id] = {
            "decision": decision,
            "edited_action": edited_action,
        }
        # Wake any worker parked in wait_for_decision (HITL resume).
        event = self._decisions.get(thread_id)
        if event is not None:
            event.set()

    def _harness_root_dir(self) -> str:
        """Return the workspace root directory for file tools.

        :return: Root directory path string.
        """
        return self._root_dir

    def get_hitl_decision(self, thread_id: str) -> str | None:
        """Return a thread's recorded HITL decision, if any.

        :param thread_id: Thread id to read.
        :return: Decision string or None.
        """
        record = self._hitl.get(thread_id)
        return None if record is None else str(record.get("decision"))

    def get_hitl_edited_action(self, thread_id: str) -> dict[str, Any] | None:
        """Return the reviewer-edited action arguments, if any.

        :param thread_id: Thread id to read.
        :return: Edited action mapping or None.
        """
        record = self._hitl.get(thread_id)
        if record is None:
            return None
        edited = record.get("edited_action")
        return edited if isinstance(edited, dict) else None

    async def wait_for_decision(self, thread_id: str) -> str | None:
        """Wait until a HITL decision lands for a thread.

        A worker calls this after publishing ``hitl_requested``; it
        resolves when :meth:`set_hitl_decision` records the human
        choice or :meth:`cancel` wakes the waiter.

        :param thread_id: Thread id awaiting review.
        :return: Decision string, or None when woken by cancel.
        """
        event = self._decisions.get(thread_id)
        if event is None:
            return None
        await event.wait()
        decision = self.get_hitl_decision(thread_id)
        # On cancel (decision None), cleaned; if edit, edited_action preserved in _hitl.
        return decision
