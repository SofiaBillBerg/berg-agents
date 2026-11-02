"""Server-owned agent runs for the chat surface.

The chat stream used to *be* the agent run: a POST opened an SSE response,
the run lived inside it, and the response ending killed the run. That one
fact caused three separate complaints:

* the agent had to be rebuilt for every message (nothing held it),
* a message typed while the agent worked had to abort the request to reach
  it, so mid-run messages interrupted instead of steering,
* nothing survived the browser, so a reload could leave a paused run
  unreachable.

Run ownership now belongs to the session. A session keeps one live ``Agent``
(rebuilt only when its configuration actually changes) and at most one
``LiveRun``. The run is driven by its own tasks and writes protocol chunks
into a replayable journal; HTTP responses are readers of that journal.
Closing a reader stops nothing.

The run is split into two cooperating tasks because two libraries own
different lifecycles and neither can drive both:

* the **graph driver** walks pydantic-ai's ``AgentRun`` node by node - the
  only place a run can be steered or first-party cancelled;
* the **encoder** owns a single ``VercelAIEventStream`` for the whole turn,
  because the protocol's ``start``/``finish`` frames bracket a turn and must
  not repeat per node.

Node events flow driver -> encoder -> journal, in order.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
import contextlib
from dataclasses import dataclass, field
import json
import logging
import time
from typing import Any, Literal
import uuid

logger = logging.getLogger(__name__)

#: How long a finished run's journal stays readable, so a browser that lost
#: its connection can catch up on the tail it missed. After this, readers are
#: sent to the server's history instead - the transcript is authoritative.
JOURNAL_GRACE_SECONDS = 120.0

#: Bound on journaled chunks held for one run. A run that outgrows this drops
#: its oldest chunks and marks itself truncated; the server's transcript is the
#: source of truth, so truncation is a UI staleness problem, never a lost turn.
JOURNAL_MAX_CHUNKS = 20000

#: Today's SDK protocol version. The approval wire (state ``approval-requested``
#: and friends) is version 6; 7 emits the same wire.
SDK_VERSION = 6


class RunBusyError(RuntimeError):
    """Raised when a start is requested while a run is still live."""


@dataclass(slots=True)
class RunOutcome:
    """How a run ended, as the session records it."""

    kind: Literal["completed", "paused", "cancelled", "failed"]
    detail: str = ""
    #: Tools paused waiting for the human, when the run paused on approval.
    approvals: tuple[str, ...] = ()

    @property
    def paused_for_approval(self) -> bool:
        """Whether the human now needs to answer something."""
        return self.kind == "paused" and bool(self.approvals)


@dataclass(slots=True)
class _NodeTicket:
    """One streamed node handed from the graph driver to the encoder.

    ``done`` is set by the encoder once it has fully consumed the node, so the
    driver never advances the graph under a half-streamed node.
    """

    node: Any
    done: asyncio.Event = field(default_factory=asyncio.Event)
    cancel: bool = False


class LiveRun:
    """One agent run, owned by its session rather than by a request.

    :param agent: The session's agent. Reused across runs; nothing here
        mutates it, so one build serves many messages.
    :param request: Zero-arg callable returning the ``AgentRun`` async context
        manager. Called inside the run's own task.
    :param on_finish: Called exactly once with how the run ended. Turn saving
        and guard resets live there, so they never depend on a browser.
    :param generation: Per-run counter. Clients echo it so a late approval for
        an older run cannot land on a newer one.
    :param max_duration: Wall-clock ceiling in seconds. On expiry the run
        PAUSES for approval instead of being cancelled, so work is never lost.
    :param on_consumed: Called with texts the model has now received, so the
        steering strip can move them into the transcript.
    """

    def __init__(
        self,
        *,
        agent: Any,
        request: Callable[[], Any],
        generation: int,
        max_duration: float,
        on_finish: Callable[[LiveRun, RunOutcome], Awaitable[None]]
        | None = None,
        on_consumed: Callable[[frozenset[str]], Awaitable[None]] | None = None,
    ) -> None:
        """Construct a run that has not started yet.

        :param agent: The session's agent (never mutated here).
        :param request: Zero-arg callable returning the ``AgentRun`` async
            context manager; called inside the run's own task.
        :param generation: Per-run counter echoed by clients.
        :param max_duration: Wall-clock ceiling in seconds.
        :param on_finish: Persistence hook, called once when the run ends.
        :param on_consumed: Notified with texts the model has now received.
        """
        self._agent = agent
        self._request = request
        self._on_finish = on_finish
        self._on_consumed = on_consumed
        self.generation = generation
        self.max_duration = max_duration

        # -- journal -------------------------------------------------------
        self._chunks: list[str] = []
        self._truncated = False
        self._changed = asyncio.Event()
        self._done = False
        self._outcome: RunOutcome | None = None
        self._finished_at: float | None = None
        self._failure: BaseException | None = None

        # -- driver -> encoder handoff -------------------------------------
        self._queue: list[_NodeTicket] = []
        self._queue_changed = asyncio.Event()
        self._driver_finished = False
        self._agent_run: Any = None
        self._tasks: list[asyncio.Task[None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._cancelled_reason: str | None = None

        # -- steering ------------------------------------------------------
        self._pending_steering: dict[str, str] = {}
        self._unread: list[str] = []

    # -- state -------------------------------------------------------------

    @property
    def live(self) -> bool:
        """Whether the run is still executing."""
        return not self._done

    @property
    def outcome(self) -> RunOutcome | None:
        """How the run ended, or ``None`` while it is still going."""
        return self._outcome

    @property
    def truncated(self) -> bool:
        """Whether the journal dropped its head (a reader must reload history)."""
        return self._truncated

    @property
    def agent_run(self) -> Any:
        """The pydantic-ai ``AgentRun``, or ``None`` before it starts.

        The finished run is the authoritative record of the turn: its
        ``all_messages()`` / ``new_messages()`` are what gets persisted, and
        they survive a Stop (first-party cancellation keeps completed work).
        """
        return self._agent_run

    @property
    def finished_at(self) -> float:
        """Monotonic time the run ended (``inf`` while it is still running)."""
        return (
            self._finished_at if self._finished_at is not None else float("inf")
        )

    def history(self) -> list[Any] | None:
        """The turn's model history, for resuming it.

        A run that paused on a deferred approval leaves its calls in history,
        so a resume continues from here instead of re-deriving the pause.

        :return: The run's ``all_messages()``, or ``None`` before it started.
        """
        agent_run = self._agent_run
        return agent_run.all_messages() if agent_run is not None else None

    @property
    def paused(self) -> bool:
        """Whether the run ended waiting for the human (approval or time)."""
        outcome = self._outcome
        return outcome is not None and outcome.kind == "paused"

    @property
    def pending_steering(self) -> list[tuple[str, str]]:
        """``(enqueue_id, text)`` pairs the model has not consumed yet.

        The authority for the UI's steering strip: an entry here is a message
        the agent has genuinely not read.
        """
        return list(self._pending_steering.items())

    def status(self) -> dict[str, Any]:
        """Describe the run for the UI (live state + unread steering).

        Lets a reconnecting browser see the steering strip without receiving
        any chunks: the strip must mean the same thing after a reload.

        :return: JSON-serialisable run status.
        """
        return {
            "live": self.live,
            "generation": self.generation,
            "outcome": self.outcome.kind if self.outcome else None,
            "detail": self.outcome.detail if self.outcome else "",
            "approvals": list(self.outcome.approvals) if self.outcome else [],
            "steering": [text for _, text in self._pending_steering.values()]}

    @property
    def unread_steering(self) -> list[str]:
        """Texts steered in that the run ended before the model read."""
        return list(self._unread)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the run's two tasks. Must be called on the event loop."""
        self._loop = asyncio.get_running_loop()
        self._tasks = [
            asyncio.create_task(self._drive_graph(), name="live-run.graph"),
            asyncio.create_task(self._encode(), name="live-run.encoder")]

    async def cancel(self, reason: str) -> None:
        """Stop the run for real. This is the user's explicit Stop.

        First-party cancellation keeps everything the run completed in
        history, so a Stop never throws the turn away.

        :param reason: Recorded with the outcome.
        """
        self._cancelled_reason = reason
        if self._agent_run is not None:
            with contextlib.suppress(Exception):
                self._agent_run.cancel()

    def steer(self, text: str) -> str | None:
        """Queue a mid-run message for the model's next request.

        :param text: The human's message.
        :return: The enqueue id, or ``None`` when the run has already ended
            (the caller then starts a fresh run rather than losing the text).
        """
        if self._done or self._agent_run is None:
            return None
        enqueue_id = self._agent_run.enqueue(text)
        if enqueue_id is not None:
            self._pending_steering[enqueue_id] = text
        return enqueue_id

    # -- reading -----------------------------------------------------------

    async def subscribe(self) -> AsyncIterator[str]:
        """Yield every chunk from the start of this run, then live ones.

        Replaying from the beginning is what makes a reload or a second
        browser correct: the reader rebuilds the same turn from the same
        chunks instead of joining mid-message.
        """
        index = 0
        while True:
            while index < len(self._chunks):
                yield self._chunks[index]
                index += 1
            if self._done:
                return
            self._changed.clear()
            # Re-check after clearing: a chunk appended between the loop above
            # and the clear would otherwise be missed and the reader would hang.
            if index >= len(self._chunks):
                await self._changed.wait()

    # -- graph driver ------------------------------------------------------

    async def _drive_graph(self) -> None:
        """Walk the agent graph, handing streamed nodes to the encoder."""
        try:
            async with self._request() as agent_run:
                self._agent_run = agent_run
                outcome = await self._walk(agent_run)
        except asyncio.CancelledError:
            outcome = RunOutcome(
                kind="cancelled", detail=self._cancelled_reason or "cancelled"
            )
        except Exception as exc:  # broad-exception-caught: one bad turn must not kill the chat surface
            logger.exception("agent run failed")
            self._failure = exc
            outcome = RunOutcome(kind="failed", detail=str(exc)[:500])
        finally:
            self._driver_finished = True
            self._queue_changed.set()

        self._publish(outcome)

    async def _walk(self, agent_run: Any) -> RunOutcome:
        """Advance the graph to its end, or to the time limit.

        :param agent_run: The started ``AgentRun``.
        :return: How the run ended.
        """
        deadline = time.monotonic() + self.max_duration
        node = agent_run.next_node
        while not _is_end(node):
            if time.monotonic() > deadline:
                # The limit PAUSES rather than cancels: the work so far is
                # kept and the human decides what happens next.
                self._append_text(
                    "\n\n⏸️ This run reached its time limit. Everything "
                    "done so far is saved — tell me how to continue."
                )
                return RunOutcome(
                    kind="paused",
                    detail=f"run exceeded {self.max_duration / 60:.0f} minutes",
                )
            if _node_emits_events(node):
                ticket = _NodeTicket(node=node)
                self._queue.append(ticket)
                self._queue_changed.set()
                # The encoder must finish this node before the graph advances
                # under it: a half-streamed node cannot be re-entered.
                await ticket.done.wait()
            node = await agent_run.next(node)
        return (
            self._classify_end(node) if _is_end(node) else RunOutcome("failed")
        )

    @staticmethod
    def _classify_end(node: Any) -> RunOutcome:
        """Decide completed vs paused from the run's terminal node."""
        data = getattr(node, "data", None)
        output = getattr(data, "output", None)
        if type(output).__name__ == "DeferredToolRequests":
            approvals = tuple(
                str(getattr(call, "tool_name", ""))
                for call in getattr(output, "approvals", ()) or ()
            )
            return RunOutcome(
                kind="paused", detail="awaiting approval", approvals=approvals
            )
        return RunOutcome(kind="completed")

    def _publish(self, outcome: RunOutcome) -> None:
        """Publish the outcome and hand unread steering back to the session."""
        self._done = True
        self._finished_at = time.monotonic()
        self._outcome = outcome
        self._unread = list(self._pending_steering.values())
        self._pending_steering.clear()
        self._changed.set()
        if self._on_finish is not None and self._loop is not None:
            # Wake the loop from any thread, so a run finished off-loop still
            # reports through the same path.
            self._loop.call_soon_threadsafe(self._schedule_finish, outcome)

    def _schedule_finish(self, outcome: RunOutcome) -> None:
        """Create the finish-hook task on the run's own event loop."""
        task = asyncio.create_task(self._run_finish(outcome))
        task.add_done_callback(_log_task_error)

    async def _run_finish(self, outcome: RunOutcome) -> None:
        """Run the finish hook, isolating its failures from the run."""
        try:
            if self._on_finish is not None:
                await self._on_finish(self, outcome)
        except Exception:
            logger.exception("run finish hook failed")

    # -- encoder -----------------------------------------------------------

    async def _encode(self) -> None:
        """Own the turn's single protocol encoder and journal its output."""
        from berg_agents.ui.route_handlers.chat import encode_run_stream

        try:
            async for chunk in encode_run_stream(
                self._native_events(), on_cancel=self._note_cancel
            ):
                self._append(chunk)
        except Exception:
            logger.exception("run encoder failed")

    async def _note_cancel(self, cancelled: Any) -> None:
        """Record that the run ended in a first-party cancellation."""
        self._cancelled_reason = self._cancelled_reason or str(cancelled)[:200]

    async def _native_events(self) -> AsyncIterator[Any]:
        """Yield the run's native events in graph order."""
        index = 0
        while True:
            if index < len(self._queue):
                ticket = self._queue[index]
                index += 1
                if ticket.cancel:
                    return
                async for event in _node_events(
                    ticket.node, self._agent_run.ctx
                ):
                    yield event
                ticket.done.set()
                continue
            if self._driver_finished:
                return
            self._queue_changed.clear()
            if index >= len(self._queue) and not self._driver_finished:
                await self._queue_changed.wait()

    # -- journal -----------------------------------------------------------

    def _append(self, chunk: str) -> None:
        """Journal one encoded chunk and wake readers."""
        if len(self._chunks) >= JOURNAL_MAX_CHUNKS:
            # Keep the recent tail; a reader that lost the head is told to
            # reload from history, which is always correct.
            del self._chunks[: JOURNAL_MAX_CHUNKS // 4]
            self._truncated = True
        self._chunks.append(chunk)
        self._changed.set()
        if self._pending_steering:
            self._consume_steering(chunk)

    def _consume_steering(self, chunk: str) -> None:
        """Drop steering entries whose text the model has now received.

        Delivery is observed on the wire: the protocol reports enqueued
        messages keyed by the id ``run.enqueue()`` returned, so "consumed"
        means exactly what the transcript will show - matched by id, never by
        text, so two identical messages cannot cancel each other out.
        """
        if not self._pending_steering or "enqueued" not in chunk:
            return
        enqueue_id = _enqueued_chunk_id(chunk)
        if enqueue_id is None or enqueue_id not in self._pending_steering:
            return
        text = self._pending_steering.pop(enqueue_id)
        if self._on_consumed is not None:
            task = asyncio.create_task(self._on_consumed(frozenset({text})))
            task.add_done_callback(_log_task_error)

    def _append_text(self, text: str) -> None:
        """Journal a plain assistant text chunk (the time-limit notice)."""
        from pydantic_ai.ui.vercel_ai.request_types import (
            TextDeltaChunk,
            TextEndChunk,
            TextStartChunk,
        )

        part_id = str(uuid.uuid4())
        for chunk in (
            TextStartChunk(type="text-start", id=part_id),
            TextDeltaChunk(type="text-delta", id=part_id, delta=text),
            TextEndChunk(type="text-end", id=part_id),
        ):
            self._append(f"data: {chunk.encode(SDK_VERSION)}\n\n")


@dataclass
class SessionRuntime:
    """Everything a chat session keeps between requests.

    ``agent`` is the expensive part (model resolution, skills, MCP toolsets,
    Shared Context) and is rebuilt only when ``fingerprint`` changes. ``run``
    is the at-most-one live run; ``generation`` makes a late approval for an
    older run impossible to apply to a newer one.
    """

    session_id: str
    agent: Any
    fingerprint: tuple[Any, ...]
    run: LiveRun | None = None
    generation: int = 0
    last_used: float = field(default_factory=time.monotonic)


class RunRegistry:
    """Process-wide map from session id to :class:`SessionRuntime`.

    Mirrors ``app.state.harness``: one instance per app, created in
    ``create_app``. Held on app state rather than in a module global so two
    apps (tests, embedded use) never share agents.
    """

    def __init__(self) -> None:
        """Create an empty registry (one per app, on ``app.state``)."""
        self._runtimes: dict[str, SessionRuntime] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, session_id: str) -> SessionRuntime | None:
        """Return a session's runtime, or ``None`` when it has none."""
        runtime = self._runtimes.get(session_id)
        if runtime is not None:
            runtime.last_used = time.monotonic()
        return runtime

    def put(self, runtime: SessionRuntime) -> None:
        """Register (or replace) a session's runtime."""
        self._runtimes[runtime.session_id] = runtime

    def live_run(self, session_id: str) -> LiveRun | None:
        """Return the session's run while it is executing, else ``None``."""
        runtime = self._runtimes.get(session_id)
        if runtime is None or runtime.run is None:
            return None
        return runtime.run if runtime.run.live else None

    def lock(self, session_id: str) -> asyncio.Lock:
        """Per-session lock: two messages must never start two runs."""
        return self._locks.setdefault(session_id, asyncio.Lock())

    def prune_finished(self) -> None:
        """Release finished runs past their journal grace period."""
        now = time.monotonic()
        for runtime in self._runtimes.values():
            run = runtime.run
            if run is None or run.live:
                continue
            if now - run.finished_at > JOURNAL_GRACE_SECONDS:
                runtime.run = None


def _enqueued_chunk_id(chunk: str) -> str | None:
    """Return the enqueue id of a ``data-enqueued-messages`` SSE frame.

    The protocol keys that frame on the id ``run.enqueue()`` handed out, which
    is what makes a queued steering message exactly traceable to its delivery.

    :param chunk: One SSE frame (``data: {...}``).
    :return: The enqueue id, or ``None`` for any other frame.
    """
    try:
        payload = json.loads(chunk.removeprefix("data: ").strip())
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "data-enqueued-messages":
        return None
    enqueue_id = payload.get("id")
    return enqueue_id if isinstance(enqueue_id, str) else None


def _log_task_error(task: asyncio.Task[Any]) -> None:
    """Log a background callback failure instead of swallowing it."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("background run callback failed: %s", exc)


def _is_end(node: Any) -> bool:
    """Whether ``node`` is the graph's End marker."""
    return type(node).__name__ == "End"


def _node_emits_events(node: Any) -> bool:
    """Whether a graph node produces protocol events (model call or tool run)."""
    return type(node).__name__ in {"ModelRequestNode", "CallToolsNode"}


async def _node_events(node: Any, ctx: Any) -> AsyncIterator[Any]:
    """Stream one node's native events."""
    async with node.stream(ctx) as node_stream:
        async for event in node_stream:
            yield event
