"""core/stream.py — v2 protocol stream adapter.

Converts typed `LoopEvent` instances (from `core.loop.BergLoop`) into
`ProtocolEvent` envelopes that the existing web UI / TUI already speak.

§1 of the Phase 2-3 design contract locks the `method` and
`params.data.event` values; this module is the *only* place in the
codebase that maps between the typed envelope and the wire envelope.

Mapping rules (locked by the design contract):

    | LoopEvent       | method    | params.data.event | payload keys           |
    |-----------------|-----------|-------------------|------------------------|
    | RunStarted      | lifecycle | run-started       | thread_id              |
    | RunCompleted    | lifecycle | run-completed     | thread_id,steps,tool_calls,final_message |
    | RunError        | lifecycle | run-error         | thread_id,error,step   |
    | RunCancelled    | lifecycle | run-cancelled     | thread_id,reason       |
    | StepStart       | lifecycle | step-start        | step,max_steps         |
    | StepEnd         | lifecycle | step-end          | step,tool_calls        |
    | HitlRequired    | lifecycle | hitl-required     | call_id,tool_name,tool_args,allowed_decisions,reason |
    | HitlResolved    | lifecycle | hitl-resolved     | call_id,decision       |
    | ContentDelta    | messages  | content-block-delta| index,text              |
    | MessageFinish   | messages  | message-finish    | message                |
    | ToolCallRequest | messages  | tool-call         | call_id,tool_name,tool_args |
    | ToolCallResult  | messages  | tool-result       | call_id,tool_name,output,error,duration_ms |
    | ToolStart       | tools     | tool-start        | call_id,tool_name,tool_args |
    | ToolEnd         | tools     | tool-end          | call_id,tool_name,output,duration_ms |
    | ToolError       | tools     | tool-error        | call_id,tool_name,error |

Heartbeat and `state` events are emitted by other layers (transport /
checkpointer) — `StreamAdapter` never produces them.

The adapter is intentionally minimal: no buffering, no async, no
transport.  The HTTP / SSE / TUI layers pull `ProtocolEvent`s by
iterating the adapter; they decide when to flush, broadcast, and
heartbeat.
"""

from __future__ import annotations

from collections.abc import Iterator

from berg_agents.core.chat_server import ProtocolEvent
from berg_agents.core.loop import (
    ContentDelta,
    HitlRequired,
    HitlResolved,
    LoopEvent,
    MessageFinish,
    RunCancelled,
    RunCompleted,
    RunError,
    RunStarted,
    StepEnd,
    StepStart,
    ToolCallRequest,
    ToolCallResult,
    ToolEnd,
    ToolError,
    ToolStart,
)

__all__ = ["StreamAdapter", "loop_event_to_protocol_event"]


def loop_event_to_protocol_event(  # ruff: ignore[complex-structure]
    event: LoopEvent, *, seq: int
) -> ProtocolEvent:
    """Map one typed :class:`LoopEvent` to one :class:`ProtocolEvent`.

    Pure function — no I/O, no shared state.  The StreamAdapter owns
    the seq counter; this helper just stamps it on.
    """
    if isinstance(event, RunStarted):
        return ProtocolEvent(
            id=seq,
            event="lifecycle",
            data={
                "event": "run-started",
                "thread_id": event.thread_id,
                "input_messages": [dict(m) for m in event.input_messages],
            },
        )

    if isinstance(event, RunCompleted):
        return ProtocolEvent(
            id=seq,
            event="lifecycle",
            data={
                "event": "run-completed",
                "thread_id": event.thread_id,
                "steps": event.steps,
                "tool_calls": event.tool_calls,
                "final_message": event.final_message,
            },
        )

    if isinstance(event, RunError):
        return ProtocolEvent(
            id=seq,
            event="lifecycle",
            data={
                "event": "run-error",
                "thread_id": event.thread_id,
                "error": event.error,
                "step": event.step,
            },
        )

    if isinstance(event, RunCancelled):
        return ProtocolEvent(
            id=seq,
            event="lifecycle",
            data={
                "event": "run-cancelled",
                "thread_id": event.thread_id,
                "reason": event.reason,
                "step": event.step,
            },
        )

    if isinstance(event, StepStart):
        return ProtocolEvent(
            id=seq,
            event="lifecycle",
            data={
                "event": "step-start",
                "step": event.step,
                "max_steps": event.max_steps,
            },
        )

    if isinstance(event, StepEnd):
        return ProtocolEvent(
            id=seq,
            event="lifecycle",
            data={
                "event": "step-end",
                "step": event.step,
            },
        )

    if isinstance(event, HitlRequired):
        return ProtocolEvent(
            id=seq,
            event="lifecycle",
            data={
                "event": "hitl-required",
                "call_id": event.call_id,
                "tool_name": event.tool_name,
                "tool_args": dict(event.tool_args),
                "allowed_decisions": list(event.allowed_decisions),
                "reason": event.reason,
            },
        )

    if isinstance(event, HitlResolved):
        return ProtocolEvent(
            id=seq,
            event="lifecycle",
            data={
                "event": "hitl-resolved",
                "call_id": event.call_id,
                "decision": event.decision,
            },
        )

    if isinstance(event, ContentDelta):
        return ProtocolEvent(
            id=seq,
            event="messages",
            data={
                "event": "content-block-delta",
                "index": event.index,
                "text": event.text,
            },
        )

    if isinstance(event, MessageFinish):
        return ProtocolEvent(
            id=seq,
            event="messages",
            data={
                "event": "message-finish",
                "message": dict(event.message),
            },
        )

    if isinstance(event, ToolCallRequest):
        return ProtocolEvent(
            id=seq,
            event="messages",
            data={
                "event": "tool-call",
                "call_id": event.call_id,
                "tool_name": event.tool_name,
                "tool_args": dict(event.tool_args),
            },
        )

    if isinstance(event, ToolCallResult):
        return ProtocolEvent(
            id=seq,
            event="messages",
            data={
                "event": "tool-result",
                "call_id": event.call_id,
                "tool_name": event.tool_name,
                "output": event.output,
                "error": event.error,
                "duration_ms": event.duration_ms,
            },
        )

    if isinstance(event, ToolStart):
        return ProtocolEvent(
            id=seq,
            event="tools",
            data={
                "event": "tool-start",
                "call_id": event.call_id,
                "tool_name": event.tool_name,
                "tool_args": dict(event.tool_args),
            },
        )

    if isinstance(event, ToolEnd):
        return ProtocolEvent(
            id=seq,
            event="tools",
            data={
                "event": "tool-end",
                "call_id": event.call_id,
                "tool_name": event.tool_name,
                "output": event.output,
                "duration_ms": event.duration_ms,
            },
        )

    if isinstance(event, ToolError):
        return ProtocolEvent(
            id=seq,
            event="tools",
            data={
                "event": "tool-error",
                "call_id": event.call_id,
                "tool_name": event.tool_name,
                "error": event.error,
            },
        )

    # Exhaustive isinstance chain above — if a new LoopEvent variant is
    # added without extending this function, the line below will raise
    # at runtime.  This is intentional: the v2 protocol mapping is a
    # contract, not a default.
    raise TypeError(f"unknown LoopEvent variant: {type(event).__name__}")


class StreamAdapter:
    """Wrap an :class:`Iterator[LoopEvent]` into :class:`Iterator[ProtocolEvent]`.

    The adapter owns a monotonic `seq` counter (default start: 0, but
    can be offset to resume from a known position).  The mapping table
    is in :func:`loop_event_to_protocol_event`; this class only adds
    iteration + seq bookkeeping.

    The adapter is single-use: each call to :meth:`__iter__` exhausts
    the source iterator.  Re-iterate the source to start a new stream.
    """

    __slots__ = ("_events", "_seq")

    def __init__(  # ruff: ignore[undocumented-public-init]
        self,
        events: Iterator[LoopEvent],
        *,
        starting_seq: int = 0,
    ) -> None:
        if starting_seq < 0:
            raise ValueError(f"starting_seq must be >= 0, got {starting_seq!r}")
        self._events = events
        self._seq = starting_seq

    @property
    def seq(self) -> int:
        """The seq number the **next** event will be stamped with."""
        return self._seq

    def __iter__(self) -> Iterator[ProtocolEvent]:
        """Yield one :class:`ProtocolEvent` per source :class:`LoopEvent`."""
        for event in self._events:
            yield loop_event_to_protocol_event(event, seq=self._seq)
            self._seq += 1
