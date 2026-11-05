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

#: How often the registry sweeps finished runs and idle sessions. Short enough
#: that a released journal is invisible, long enough to cost nothing.
SWEEP_INTERVAL_SECONDS = 30.0

#: How long the encoder gets to flush a turn's closing frames after the graph
#: driver stops. Past this it is cancelled: a wedged stream must never keep a
#: run reported ``live`` forever.
ENCODER_CLOSE_GRACE_SECONDS = 10.0

#: How long a session keeps a warm agent with no traffic. The plan wanted
#: "keep warm for the life of the process, evict only under pressure"; a bound
#: is cheaper to reason about and the rebuild is one fingerprint check away.
INTERACTIVE_IDLE_SECONDS = 60.0 * 60.0

#: Bound on journaled chunks held for one run. A run that outgrows this drops
#: its oldest chunks and marks itself truncated; the server's transcript is the
#: source of truth, so truncation is a UI staleness problem, never a lost turn.
JOURNAL_MAX_CHUNKS = 20000

#: Today's SDK protocol version. The approval wire (state ``approval-requested``
#: and friends) is version 6; 7 emits the same wire.
SDK_VERSION = 6


class StaleAnswerError(RuntimeError):
    """Raised when a deferred answer (approval or question) answers a run that has already ended or was already applied."""


@dataclass(slots=True)
class RunOutcome:
    """How a run ended, as the session records it."""

    kind: Literal["completed", "paused", "cancelled", "failed"]
    detail: str = ""
    #: Tools paused waiting for an approve/reject decision.
    approvals: tuple[str, ...] = ()
    #: Tools paused waiting for an answer the human must produce
    #: (``ask_user_question`` defers as an external call, not an approval).
    questions: tuple[str, ...] = ()

    @property
    def paused_for_answer(self) -> bool:
        """Whether the human now needs to answer something.

        A pause is a pause whether the run wants a decision or an answer -
        one HITL surface answers both.
        """
        return self.kind == "paused" and bool(self.approvals or self.questions)


@dataclass(slots=True)
class _NodeTicket:
    """One item handed from the graph driver to the encoder.

    Either a node to stream (its native events go on the wire) or the run's
    closing result. ``done`` is set by the encoder once it has fully consumed
    the item, so the driver never advances the graph under a half-streamed
    node, and never finishes the run before its result has been encoded.

    The closing result is what makes a pause visible to the human: the
    protocol's approval chunk is derived from the run's final
    ``DeferredToolRequests`` output, so a run that paused without sending its
    result would show as merely "tool input available" and no approve/reject
    UI would ever appear.
    """

    node: Any = None
    result: Any = None
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
    :param max_duration: Wall-clock ceiling in seconds for the no-tool-call
        backstop in :meth:`_walk` (see
        :class:`~berg_agents.capabilities.wall_clock_guard.WallClockGuard` for
        the approval-card path). On expiry the run PAUSES, not cancels, so
        work is never lost.
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
            "questions": list(self.outcome.questions) if self.outcome else [],
            "steering": list(self._pending_steering.values())}

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
        history, so a Stop never throws the turn away. Both halves of the run
        are released - the graph walk and the encoder - so a cancelled run
        always ends and its readers are released.

        :param reason: Recorded with the outcome.
        """
        self._cancelled_reason = reason
        if self._agent_run is not None:
            with contextlib.suppress(Exception):
                self._agent_run.cancel()
        current = asyncio.current_task()
        for task in self._tasks:
            # Never cancel the caller's own task when a run stops itself.
            if task is not current:
                task.cancel()

    def steer(self, text: str) -> str | None:
        """Queue a mid-run message for the model's next request.

        Registering the message is synchronous and cannot fail on its own: it
        either joins the run's pending queue or the run has gone, which the
        return value reports.

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
            # Journal the failure as visible text. Without it the stream
            # simply stops: the browser keeps its spinner over an empty turn
            # and never learns the run died.
            self._append_text(f"\n\n❌ This turn failed: {str(exc)[:500]}")
            # Any node the encoder is still parked on will never complete:
            # release its ticket or the wait below deadlocks.
            self._abandon_tickets()
            outcome = RunOutcome(kind="failed", detail=str(exc)[:500])

        # The outcome is published only after the encoder has closed the turn
        # on the wire. A reader subscribes until the run is over, so finishing
        # first would end every open stream mid-turn - the browser then sees a
        # turn that stopped but is still reported live, and loses the frames
        # that describe how it ended (an approval request above all).
        try:
            await self._wait_for_encoder()
        finally:
            self._publish(outcome)

    async def _wait_for_encoder(self) -> None:
        """Release the encoder so it flushes the turn's closing frames.

        Bounded: an encoder that cannot close within the grace period is
        cancelled rather than awaited forever, so a wedged protocol stream can
        never leave the run ``live`` with no way back to idle.
        """
        self._driver_finished = True
        self._queue_changed.set()
        for task in self._tasks:
            if (
                task.get_name() == "live-run.encoder"
                and task is not asyncio.current_task()
            ):
                done, _pending = await asyncio.wait(
                    {task}, timeout=ENCODER_CLOSE_GRACE_SECONDS
                )
                if not done:
                    logger.warning(
                        "Encoder did not close within %.0fs; cancelling it",
                        ENCODER_CLOSE_GRACE_SECONDS,
                    )
                    task.cancel()

    async def _walk(self, agent_run: Any) -> RunOutcome:
        """Advance the graph to its end, or to the time limit.

        The time limit normally reaches the human through
        :class:`~berg_agents.capabilities.wall_clock_guard.WallClockGuard`,
        which defers the next tool call so the run pauses on a real approval
        card. This walk's check is the backstop for the one case a capability
        cannot cover: no tool call comes up before the clock runs out (a single
        very long model request, or a tool that never returns). The human then
        gets plain text instead of a card - the honest fallback, because there
        is no call to attach a decision to.

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
                    "\n\n⏸️ This run reached its time limit without reaching "
                    "a tool call to ask about. Everything done so far is "
                    "saved — tell me how to continue."
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
                # under it: a half-streamed node cannot be re-entered. This
                # wait is deliberately UNBOUNDED: a node streams for exactly
                # as long as the model or tool takes, so any timeout here
                # would advance the graph under a live stream and corrupt the
                # run. Deadlock is prevented at the source instead - every
                # encoder death path releases queued tickets (see _encode).
                await self._wait_ticket(ticket)
            node = await agent_run.next(node)
        if not _is_end(node):
            return RunOutcome("failed")
        outcome = self._classify_end(node)
        await self._deliver_result(agent_run)
        return outcome

    @staticmethod
    async def _wait_ticket(ticket: Any, *, bounded: bool = False) -> None:
        """Wait for the encoder to finish a ticket.

        Unbounded for a node ticket: the node streams for exactly as long as
        the model or tool takes - minutes for a long response - and a timeout
        here would advance the graph under a live stream, which pydantic-ai
        rejects ("You must finish streaming before calling run()"). The wait
        cannot deadlock: every encoder death path releases queued tickets
        (see :meth:`_encode`), and a wedged run is recoverable with Stop.

        Bounded for the run's closing result: the graph has already finished,
        so a wedged encoder must not hold the run ``live`` forever.
        :meth:`_wait_for_encoder` cancels it past the same grace anyway.

        :param ticket: The queued :class:`_NodeTicket` to wait on.
        :param bounded: Grace-bound the wait; used only for the closing
            result, never for a node.
        """
        if not bounded:
            await ticket.done.wait()
            return
        try:
            await asyncio.wait_for(
                ticket.done.wait(), timeout=ENCODER_CLOSE_GRACE_SECONDS
            )
        except TimeoutError:
            logger.warning(
                "Encoder did not take the closing result within %.0fs",
                ENCODER_CLOSE_GRACE_SECONDS,
            )

    async def _deliver_result(self, agent_run: Any) -> None:
        """Hand the run's final result to the encoder before finishing.

        The protocol builds its closing frames - the approval request above
        all - from the run result, so the encoder must see it. The walk above
        drives the graph by hand and therefore never yields one itself.
        """
        ticket = _NodeTicket(result=agent_run.result)
        self._queue.append(ticket)
        self._queue_changed.set()
        await self._wait_ticket(ticket, bounded=True)

    def _abandon_tickets(self) -> None:
        """Release every queued ticket after the graph died under the encoder.

        The encoder may be parked on ``ticket.done`` for a node the graph will
        never finish streaming. Without this the two tasks deadlock forever:
        the driver waits for the encoder to close the turn, the encoder waits
        for a node that no longer exists, and the run stays ``live`` for the
        life of the process (the browser's spinner never clears).
        """
        for ticket in self._queue:
            ticket.done.set()

    @staticmethod
    def _classify_end(node: Any) -> RunOutcome:
        """Decide completed vs paused from the run's terminal node.

        A deferral is not always an approval: ``requires_approval`` tools
        wait in ``approvals``, while externally-executed calls
        (``ask_user_question``) wait in ``calls``. The outcome reports what
        the human actually owes an answer for - a blanket "awaiting
        approval" over a question pause is how the webapp ended up with an
        unanswerable session and a status that lied about why.
        """
        data = getattr(node, "data", None)
        output = getattr(data, "output", None)
        if type(output).__name__ == "DeferredToolRequests":
            approvals = tuple(
                str(getattr(call, "tool_name", ""))
                for call in getattr(output, "approvals", ()) or ()
            )
            questions = tuple(
                str(getattr(call, "tool_name", ""))
                for call in getattr(output, "calls", ()) or ()
            )
            owed = " and ".join(
                what
                for what, names in (
                    ("approval", approvals),
                    ("answers", questions),
                )
                if names
            )
            return RunOutcome(
                kind="paused",
                detail=f"awaiting {owed}",
                approvals=approvals,
                questions=questions,
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

        events = self._native_events()
        try:
            async for chunk in encode_run_stream(
                events, on_cancel=self._note_cancel
            ):
                self._append(chunk)
        except asyncio.CancelledError:
            # Shutdown or a wedged stream. First close the native-events
            # generator: it may be suspended inside a node's stream context,
            # and unwinding that is what lets the graph advance past the
            # node. Then release anything the driver is parked on, or that
            # await never returns and the run stays live for the life of the
            # process. Last, let the cancellation propagate.
            with contextlib.suppress(Exception):
                await events.aclose()
            self._abandon_tickets()
            raise
        except Exception:
            logger.exception("run encoder failed")
            # Same two-step as the cancel branch: unwind any half-streamed
            # node, then release the driver's tickets.
            with contextlib.suppress(Exception):
                await events.aclose()
            self._abandon_tickets()

    async def _note_cancel(self, cancelled: Any) -> None:
        """Record that the run ended in a first-party cancellation."""
        self._cancelled_reason = self._cancelled_reason or str(cancelled)[:200]

    async def _native_events(self) -> AsyncIterator[Any]:
        """Yield the run's native events in graph order, ending with its result."""
        index = 0
        while True:
            if index < len(self._queue):
                ticket = self._queue[index]
                index += 1
                if ticket.cancel:
                    # The driver may already be parked on this ticket. Release
                    # it before leaving, or that await never returns and the
                    # run stays live for the life of the process.
                    ticket.done.set()
                    return
                if ticket.result is not None:
                    yield _run_result_event(ticket.result)
                else:
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
        from pydantic_ai.ui.vercel_ai.response_types import (
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

    def prune_idle(self, max_idle_seconds: float) -> None:
        """Drop session runtimes untouched for ``max_idle_seconds``.

        Only idle sessions go: a runtime that still holds a live run is in
        use by definition, and dropping its agent would rebuild it under a
        running turn.

        :param max_idle_seconds: Age past ``last_used`` that counts as idle.
        """
        now = time.monotonic()
        stale = [
            session_id
            for session_id, runtime in self._runtimes.items()
            if (runtime.run is None or not runtime.run.live)
            and now - runtime.last_used > max_idle_seconds
        ]
        for session_id in stale:
            logger.info("Releasing idle session runtime %s", session_id)
            del self._runtimes[session_id]
            self._locks.pop(session_id, None)

    async def sweep(self, interval_seconds: float) -> None:
        """Run :meth:`prune_finished` forever, once per ``interval_seconds``.

        Without a sweeper nothing ever calls ``prune_finished``: a finished
        run keeps its journal alive, and its session keeps a warm agent, for
        the life of the process. Started by the server lifespan and cancelled
        with it.

        :param interval_seconds: Pause between sweeps.
        """
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                self.prune_finished()
                self.prune_idle(INTERACTIVE_IDLE_SECONDS)
            except Exception:  # keep the sweeper alive; log the failure
                logger.exception("Run registry sweep failed")


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


def _run_result_event(result: Any) -> Any:
    """Wrap a run's final result as the event the encoder closes the turn with.

    ``run_stream`` closes with exactly this event, and the protocol derives its
    closing frames from it. A hand-driven graph walk has to hand it over
    itself, or the turn ends without the frames that describe how it ended.

    :param result: The run's ``AgentRunResult``.
    :return: The corresponding ``AgentRunResultEvent``.
    """
    from pydantic_ai.run import AgentRunResultEvent

    return AgentRunResultEvent(result=result)
