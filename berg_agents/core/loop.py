"""Framework-free agentic tool-calling loop.

The :class:`BergLoop` is the heart of Phase 2-3: it drives the LLM
through tool calls until the model stops requesting tools (or the
caller's ``interrupt_on`` policy pauses the cycle, or ``max_steps`` is
hit, or an exception escapes).  It yields typed :class:`LoopEvent`
values; the caller wraps them into ``ProtocolEvent`` (see
:mod:`core.stream`) and persists checkpoints (see :mod:`core.checkpoint`).

Why no framework?  Three reasons:

1. **Determinism.**  A pure-Python generator we can replay in tests
   is easier to verify than a callback-driven state machine.  The
   whole loop fits in one file with no implicit state.
2. **Surface stability.**  The v2 protocol envelope (``core.chat_server``)
   is the wire contract.  The loop emits typed events; a thin
   adapter (``core.stream.StreamAdapter``) maps them to envelopes.
   Either side can change without dragging the other.
3. **Framework-agnostic.**  The :class:`NativeAdapter` and the
   :class:`ToolRegistry` are the only abstractions the loop depends
   on.  Swapping the LLM provider means writing a new adapter, not
   patching the loop.

Concurrency model
-----------------

The loop is **not thread-safe** per ``thread_id``.  The expected
pattern is one ``BergLoop`` per thread, with the checkpointer
serialising state across processes.  The ``cancel`` method sets a
flag that the running generator checks at every step boundary; this
works because Python generators are cooperatively scheduled and
``send``/``next`` interleave at ``yield`` points.

Streaming
---------

The current :class:`BackendAdapter` returns a *complete* chat-completion
dict (``adapter.chat(...)``).  When streaming lands in Phase 2-4,
the loop will switch to ``adapter.stream_chat(...)`` and emit
``ContentDelta`` events as tokens arrive.  For now the loop emits
*one* ``MessageFinish`` per assistant message and no deltas - the
adapter simply has no delta source.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass
import json
import logging
import time
from typing import Any
import uuid

from berg_agents.core.checkpoint import Checkpointer, make_snapshot
from berg_agents.core.hitl import (
    HitlDecision,
    HitlRequest,
    apply_decision,
    default_interrupt_on,
    is_valid_decision,
)
from berg_agents.core.tool_spec import ToolRegistry, effective_risk_class

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LoopEvent dataclasses (16 variants - see design-contract §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunStarted:
    """The cycle has begun.  Emitted exactly once at the top of :meth:`BergLoop.run`.

    :attr:`thread_id` is the thread that started.
    :attr:`input_messages` is the list of input messages.
    """

    thread_id: str
    input_messages: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class RunCompleted:
    """The cycle ended without errors, HITL pause, or cancellation.

    :attr:`final_message` is the last assistant message.
    :attr:`steps` is the number of steps taken.
    :attr:`tool_calls` is the number of tool calls made.
    :attr:`thread_id` is the thread that completed.
    """

    thread_id: str
    final_message: Mapping[str, Any]
    steps: int
    tool_calls: int


@dataclass(frozen=True)
class RunError:
    """The cycle ended because of an unrecoverable error.

    Includes :class:`RuntimeError` from the LLM adapter,
    :class:`TimeoutError`, the loop's own ``max_steps`` limit, or
    any other exception that escaped a tool call.

    :attr:`step` is the index of the step that failed.
    :attr:`thread_id` is the thread that failed.
    :attr:`error` is the error message.
    """

    thread_id: str
    error: str
    step: int


@dataclass(frozen=True)
class RunCancelled:
    """The cycle ended because :meth:`BergLoop.cancel` was called.

    :attr:`reason` is the reason for the cancellation.
    :attr:`step` is the index of the step that was cancelled.
    :attr:`thread_id` is the thread that was cancelled.
    """

    thread_id: str
    reason: str
    step: int


@dataclass(frozen=True)
class StepStart:
    """A new step is about to begin (one LLM call + N tool calls).

    :attr:`step` is the index of the step that is about to start; the next step will be `step + 1`.
    :attr:`max_steps` is the configured maximum number of steps for the loop.
    """

    step: int
    max_steps: int


@dataclass(frozen=True)
class StepEnd:
    """A step has finished.

    :attr:`step` is the index of the step that just finished; the next step will be `step + 1`.
    """

    step: int


@dataclass(frozen=True)
class ContentDelta:
    """A streaming content delta.  Phase 2-3 emits *zero* of these
    (no streaming adapter yet); the dataclass is in place for
    Phase 2-4.
    """

    index: int
    text: str


@dataclass(frozen=True)
class MessageFinish:
    """The assistant message is complete.  ``message`` is the OpenAI-shaped dict."""

    message: Mapping[str, Any]


@dataclass(frozen=True)
class ToolCallRequest:
    """The model decided to call a tool.  Loop will dispatch + decide HITL."""

    call_id: str
    tool_name: str
    tool_args: Mapping[str, Any]


@dataclass(frozen=True)
class ToolCallResult:
    """Dispatched tool returned.  Loop will feed back to the model."""

    call_id: str
    tool_name: str
    output: Any
    error: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True)
class ToolStart:
    """A tool is about to execute.  Emitted just before :attr:`ToolSpec.execute`."""

    call_id: str
    tool_name: str
    tool_args: Mapping[str, Any]


@dataclass(frozen=True)
class ToolEnd:
    """A tool finished successfully."""

    call_id: str
    tool_name: str
    output: Any
    duration_ms: int


@dataclass(frozen=True)
class ToolError:
    """A tool raised an exception.  The loop captures the message and
    feeds it back to the model as a ``tool`` role error.

    :attr:`ToolSpec.execute` exceptions are caught and wrapped in this event;
    the loop never lets exceptions escape to the caller.
    :attr:`ToolCallResult.error` is set to the exception message.
    :attr:`ToolCallResult.output` is ``None``.
    """

    call_id: str
    tool_name: str
    error: str


@dataclass(frozen=True)
class HitlRequired:
    """Pause the loop.  Caller must call :meth:`BergLoop.resume`.

    The loop yields this event when a tool call is flagged for human review.  The caller must persist the snapshot and then call :meth:`BergLoop.resume` with a :class:`HitlDecision` to continue the cycle.

    :attr:`HitlRequest` is the concrete request for human review, including the tool call ID, name, arguments, risk class, allowed decisions, and a reason string.  The caller can use this information to present a UI or CLI prompt to the human operator.
    :attr:`HitlDecision` is the human's decision on the pending request, which must be passed to :meth:`BergLoop.resume` to continue the cycle.
    :attr:`HitlResolved` is emitted at the top of :meth:`BergLoop.resume` to indicate that the paused call has been answered and the loop is continuing.
    :attr:`HitlRequired` is emitted at the top of :meth:`BergLoop.run` when a tool call is flagged for human review.  The caller must persist the snapshot and then call :meth:`BergLoop.resume` with a :class:`HitlDecision` to continue the cycle.
    :param call_id: The tool call ID.
    :param tool_name: The name of the tool.
    :param tool_args: The arguments for the tool call.
    """

    call_id: str
    tool_name: str
    tool_args: Mapping[str, Any]
    allowed_decisions: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class HitlResolved:
    """The paused call has been answered.  Emitted at the top of :meth:`BergLoop.resume`.

    :param call_id: The tool call ID.
    :param decision: The human's decision.
    """

    call_id: str
    decision: str


#: The union of all events the loop yields.  Callers ``isinstance``-test
#: on this; we keep it as a ``type`` alias rather than a real ``Union``
#: because we want ``LoopEvent`` to be importable as a single name.
LoopEvent = (
    RunStarted
    | RunCompleted
    | RunError
    | RunCancelled
    | StepStart
    | StepEnd
    | ContentDelta
    | MessageFinish
    | ToolCallRequest
    | ToolCallResult
    | ToolStart
    | ToolEnd
    | ToolError
    | HitlRequired
    | HitlResolved
)

# ---------------------------------------------------------------------------
# BergLoop
# ---------------------------------------------------------------------------


#: Step callback signature: receives :class:`StepStart` and :class:`StepEnd`.
StepCallback = Callable[["StepStart | StepEnd"], None]


class BergLoop:
    """Framework-free agentic tool-calling loop.

    Drives the LLM through tool calls until the model stops requesting
    tools (or the caller's ``interrupt_on`` policy pauses the cycle,
    or ``max_steps`` is hit, or an exception escapes).  Yields typed
    :class:`LoopEvent` values; the caller is responsible for wrapping
    them into ``ProtocolEvent`` (see :mod:`core.stream`) and for
    persisting checkpoints (see :mod:`core.checkpoint`).

    :param adapter: Any object with ``chat(messages, *, tools, temperature)``
        that returns the OpenAI-shaped completion dict.
    :param tool_registry: The :class:`ToolRegistry` the loop will look
        up tools in.
    :param temperature: Sampling temperature forwarded to the adapter on
        every ``chat`` call. ``0.7`` by default.
    :param interrupt_on: Optional ``{tool_name: True}`` map.  When a
        tool's name maps to ``True``, the loop pauses for HITL review
        before executing it.  ``None`` means "use the default policy"
        (mutating built-ins: ``edit_file``, ``write_file``, ``delete``,
        ``execute``).
    :param max_steps: Hard limit on the number of LLM steps.  ``25``
        by default.
    :param on_step: Optional callback invoked at every :class:`StepStart`
        and :class:`StepEnd`.  Used for logging / metrics; not
        part of the event stream.
    :param checkpointer: Optional :class:`Checkpointer` for cross-process
        resume.  If ``None``, the loop runs purely in-memory.
    """

    def __init__(
        self,
        adapter: Any,
        tool_registry: ToolRegistry,
        *,
        interrupt_on: Mapping[str, bool] | None = None,
        max_steps: int = 25,
        on_step: StepCallback | None = None,
        checkpointer: Checkpointer | None = None,
        temperature: float = 0.7,
    ) -> None:
        """Store constructor args and validate."""
        if not hasattr(adapter, "chat") or not callable(adapter.chat):
            raise TypeError(
                f"adapter must expose .chat(...), got {type(adapter).__name__}",
            )
        if not isinstance(tool_registry, ToolRegistry):
            raise TypeError(
                f"tool_registry must be a ToolRegistry, got {type(tool_registry).__name__}",
            )
        if max_steps < 1:
            raise ValueError(f"max_steps must be >= 1, got {max_steps}")
        if on_step is not None and not callable(on_step):
            raise TypeError("on_step must be callable or None")
        if interrupt_on is not None and not isinstance(interrupt_on, Mapping):
            raise TypeError("interrupt_on must be a Mapping or None")

        self._adapter = adapter
        self._registry = tool_registry
        self._max_steps = max_steps
        self._temperature = temperature
        self._on_step = on_step
        self._checkpointer = checkpointer
        # Resolve the effective policy.  If the caller passed nothing,
        # fall back to default_interrupt_on(registry).
        if interrupt_on is None:
            self._interrupt: dict[str, bool] = default_interrupt_on(
                dict(self._registry._tools.items()),
            )
        else:
            self._interrupt = dict(interrupt_on)
        # Cancel flags, keyed by thread_id.  Cleared on run end.
        self._cancel_flags: dict[str, str] = {}
        # Optional system prompt prepended to the message list on every run.
        # Callers (e.g. ``build_agent``) set this after construction.
        self.system_prompt: str | None = None

    # -- Public API --------------------------------------------------------

    def cancel(self, thread_id: str, *, reason: str = "cancelled") -> None:
        """Request cancellation of the running cycle for *thread_id*.

        The flag is checked at the top of every step.  Calling this on
        a thread with no active run is a no-op.

        :param thread_id: The thread to cancel.
        :param reason: Optional reason string for logging / metrics.
        """
        self._cancel_flags[thread_id] = reason

    def run(
        self,
        thread_id: str,
        input_messages: Sequence[Mapping[str, Any]],
    ) -> Generator[
        RunStarted
        | RunCancelled
        | StepStart
        | RunError
        | MessageFinish
        | StepEnd
        | RunCompleted
        | ToolCallRequest
        | HitlRequired
        | Any,
        Any,
        None]:
        """Drive the cycle.  Yields :class:`LoopEvent` values.

        Stops on terminal events (:class:`RunCompleted` /
        :class:`RunError` / :class:`RunCancelled`) or when
        :class:`HitlRequired` is emitted (caller drives
        :meth:`resume`).

        :param thread_id: The thread to resume.
        :param decision: The human's decision on the pending HITL request.
        :return: Yields :class:`LoopEvent` values until the cycle ends.
        """
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("thread_id must be a non-empty string")
        if not isinstance(input_messages, Sequence):
            raise TypeError("input_messages must be a Sequence of mappings")

        # Clear any stale cancel flag from a previous run.
        self._cancel_flags.pop(thread_id, None)

        messages: list[dict[str, Any]] = [dict(m) for m in input_messages]
        steps = 0
        tool_call_count = 0

        yield RunStarted(thread_id=thread_id, input_messages=tuple(messages))

        try:  # ruff: ignore[too-many-statements-in-try-clause]
            while steps < self._max_steps:
                # Cancel check at every step boundary.
                if self._is_cancelled(thread_id):
                    yield RunCancelled(
                        thread_id=thread_id,
                        reason=self._cancel_flags.pop(thread_id),
                        step=steps,
                    )
                    return

                yield self._step_start(steps)

                # Call the LLM.  Pass the OpenAI-shaped tool list.
                try:
                    response = self._adapter.chat(
                        messages,
                        tools=self._openai_tools(),
                        temperature=self._temperature,
                    )
                except Exception as exc:  # ruff: ignore[blind-except]
                    yield RunError(
                        thread_id=thread_id,
                        error=f"{type(exc).__name__}: {exc}",
                        step=steps,
                    )
                    return

                # The adapter returns an OpenAI completion; the assistant
                # message is the first (and only) choice.
                message = _extract_assistant_message(response)
                messages.append(dict(message))
                yield MessageFinish(message=message)

                # Did the model want to call any tools?
                tool_calls = _extract_tool_calls(message)
                if not tool_calls:
                    # No tools → run is done.
                    yield StepEnd(step=steps)
                    if self._on_step is not None:
                        self._on_step(StepEnd(step=steps))
                    yield RunCompleted(
                        thread_id=thread_id,
                        final_message=message,
                        steps=steps + 1,
                        tool_calls=tool_call_count,
                    )
                    return

                # Dispatch each tool call.  A HITL pause short-circuits
                # the loop: we yield HitlRequired, persist the snapshot
                # with the pending request, and return.
                step_interrupted = False
                for tc in tool_calls:
                    call_id = tc["id"]
                    name = tc["name"]
                    args = tc["args"]
                    yield ToolCallRequest(
                        call_id=call_id,
                        tool_name=name,
                        tool_args=args,
                    )

                    if self._interrupt.get(name, False):
                        # Pause for human review.
                        risk = self._risk_for(name)

                        # Build a concrete action declaration for HITL visibility.
                        def _hitl_reason(
                            name: str, args: Mapping[str, Any]
                        ) -> str:
                            # File-writing actions: declare the target path.
                            path = (
                                args.get("path")
                                or args.get("file_path")
                                or args.get("filename")
                                or args.get("target")
                            )
                            if (
                                name
                                in {"write_file", "edit_file", "delete_file"}
                                and path
                            ):
                                return f"agent wants to {name.replace('_', ' ')} to {path}"
                            if name == "read_file" and path:
                                return f"agent wants to read file at {path}"
                            if name in {"run_command", "execute"}:
                                cmd = (
                                    args.get("command")
                                    or args.get("cmd")
                                    or args.get("args")
                                )
                                return (
                                    f"agent wants to execute shell command: {cmd}"
                                    if cmd
                                    else f"agent wants to execute {name}"
                                )
                            # External resource access.
                            url = (
                                args.get("url")
                                or args.get("uri")
                                or args.get("link")
                            )
                            if url:
                                return f"agent wants to access external resource at {url} (read)"
                            # Fallback: declare the tool + first arg key/value.
                            arg_summary = ", ".join(
                                f"{k}={v}" for k, v in list(args.items())[:2]
                            )
                            return (
                                f"agent wants to run {name} with args: {arg_summary}"
                                if arg_summary
                                else f"agent wants to run {name}"
                            )

                        hitl = HitlRequest(
                            tool_call_id=call_id,
                            tool_name=name,
                            tool_args=args,
                            risk_class=risk,
                            allowed_decisions=("approve", "reject", "edit"),
                            reason=_hitl_reason(name, args),
                        )
                        self._persist_snapshot(
                            thread_id,
                            messages=messages,
                            step=steps,
                            tool_calls=tool_call_count,
                            pending_hitl=hitl,
                        )
                        yield HitlRequired(
                            call_id=call_id,
                            tool_name=name,
                            tool_args=args,
                            allowed_decisions=hitl.allowed_decisions,
                            reason=hitl.reason,
                        )
                        step_interrupted = True
                        break

                    # Execute the tool synchronously, forwarding any
                    # ``ToolStart``/``ToolEnd``/``ToolError`` events the
                    # helper yields.
                    result = yield from self._execute_tool(
                        call_id, name, args, messages
                    )
                    if result is not None:
                        tool_call_count += 1
                    if self._is_cancelled(thread_id):
                        step_interrupted = False
                        break

                if step_interrupted:
                    # HitlRequired already yielded; loop returns.
                    return

                steps += 1
                yield StepEnd(step=steps)
                if self._on_step is not None:
                    self._on_step(StepEnd(step=steps))

                # Persist after every step.
                self._persist_snapshot(
                    thread_id,
                    messages=messages,
                    step=steps,
                    tool_calls=tool_call_count,
                    pending_hitl=None,
                )

            # Exhausted max_steps.
            yield RunError(
                thread_id=thread_id,
                error=f"max_steps ({self._max_steps}) exceeded",
                step=steps,
            )
        except Exception as exc:  # ruff: ignore[blind-except]
            # Last-ditch catch - anything that escaped the inner try.
            _LOGGER.exception("BergLoop.run failed")
            yield RunError(
                thread_id=thread_id,
                error=f"{type(exc).__name__}: {exc}",
                step=steps,
            )

    def resume(
        self,
        thread_id: str,
        decision: HitlDecision,
    ) -> Generator[LoopEvent, Any, None]:
        """Continue a paused thread after a :class:`HitlDecision`.

        The generator is stateful per ``thread_id``; the checkpointer
        lets a different process pick up the resume.

        :param thread_id: The thread to resume.
        :param decision: The human's decision on the pending HITL request.
        :return: Yields :class:`LoopEvent` values until the cycle ends.
        """
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("thread_id must be a non-empty string")
        if not isinstance(decision, HitlDecision):
            raise TypeError(
                f"decision must be a HitlDecision, got {type(decision).__name__}",
            )

        snapshot = self._load_snapshot(thread_id)
        if snapshot is None:
            yield RunError(
                thread_id=thread_id,
                error=f"no paused snapshot for thread {thread_id!r}",
                step=0,
            )
            return

        pending = snapshot.get("pending_hitl")
        if pending is None:
            yield RunError(
                thread_id=thread_id,
                error=f"thread {thread_id!r} has no pending HITL",
                step=snapshot.get("step", 0),
            )
            return

        if not is_valid_decision(pending, decision):
            yield RunError(
                thread_id=thread_id,
                error=f"decision {decision.action!r} not valid for this request",
                step=snapshot.get("step", 0),
            )
            return

        yield HitlResolved(
            call_id=decision.tool_call_id, decision=decision.action
        )

        messages: list[dict[str, Any]] = [dict(m) for m in snapshot["messages"]]
        steps = int(snapshot.get("step", 0))
        tool_call_count = int(snapshot.get("tool_calls", 0))

        # Apply the decision.  None means reject.
        final_args = apply_decision(pending, decision)
        if final_args is None:
            # Reject: feed the model a tool error and continue the cycle.
            messages.append(
                _tool_error_message(
                    pending.tool_call_id, pending.tool_name, "rejected by human"
                ),
            )
            yield ToolError(
                call_id=pending.tool_call_id,
                tool_name=pending.tool_name,
                error="rejected by human",
            )
            # Resume the main loop with the cleared pending_hitl.
            self._cancel_flags.pop(thread_id, None)
            yield from self._continue_cycle(
                thread_id,
                messages,
                steps,
                tool_call_count,
            )
            return

        # Approve or edit: execute the tool, then continue.
        yield from self._execute_tool(
            pending.tool_call_id,
            pending.tool_name,
            final_args,
            messages,
        )
        tool_call_count += 1
        # Clear the pending_hitl in the snapshot.
        self._persist_snapshot(
            thread_id,
            messages=messages,
            step=steps,
            tool_calls=tool_call_count,
            pending_hitl=None,
        )
        yield from self._continue_cycle(
            thread_id,
            messages,
            steps,
            tool_call_count,
        )

    # -- Internal helpers --------------------------------------------------

    def _continue_cycle(
        self,
        thread_id: str,
        messages: list[dict[str, Any]],
        steps: int,
        tool_call_count: int,
    ) -> Generator[LoopEvent, Any, None]:
        """Resume the main run loop after a HITL decision.

        Re-uses the same dispatch logic.  Returns when the cycle is
        complete or hits another HITL pause / cancellation / error.

        :param thread_id: The thread to resume.
        :param messages: The current message list.
        :param steps: The current step count.
        :param tool_call_count: The current tool call count.
        :return: Yields :class:`LoopEvent` values until the cycle ends.
        """
        self._cancel_flags.pop(thread_id, None)
        while steps < self._max_steps:
            if self._is_cancelled(thread_id):
                yield RunCancelled(
                    thread_id=thread_id,
                    reason=self._cancel_flags.pop(thread_id),
                    step=steps,
                )
                return
            yield self._step_start(steps)
            try:
                response = self._adapter.chat(
                    messages,
                    tools=self._openai_tools(),
                    temperature=self._temperature,
                )
            except Exception as exc:  # ruff: ignore[blind-except]
                yield RunError(
                    thread_id=thread_id,
                    error=f"{type(exc).__name__}: {exc}",
                    step=steps,
                )
                return

            message = _extract_assistant_message(response)
            messages.append(dict(message))
            yield MessageFinish(message=message)

            tool_calls = _extract_tool_calls(message)
            if not tool_calls:
                yield StepEnd(step=steps)
                yield RunCompleted(
                    thread_id=thread_id,
                    final_message=message,
                    steps=steps + 1,
                    tool_calls=tool_call_count,
                )
                return

            step_interrupted = False
            for tc in tool_calls:
                call_id = tc["id"]
                name = tc["name"]
                args = tc["args"]
                yield ToolCallRequest(
                    call_id=call_id, tool_name=name, tool_args=args
                )
                if self._interrupt.get(name, False):
                    risk = self._risk_for(name)

                    # Build concrete action declaration for HITL visibility.
                    def _hitl_reason(name: str, args: Mapping[str, Any]) -> str:
                        """File-writing actions: declare the target path.

                        :param name: tool name
                        :param args: tool args
                        :return: human-readable reason for HITL pause
                        """
                        path = (
                            args.get("path")
                            or args.get("file_path")
                            or args.get("filename")
                            or args.get("target")
                        )
                        if (
                            name in {"write_file", "edit_file", "delete_file"}
                            and path
                        ):
                            return f"agent wants to {name.replace('_', ' ')} to {path}"
                        if name == "read_file" and path:
                            return f"agent wants to read file at {path}"
                        if name in {"run_command", "execute"}:
                            cmd = (
                                args.get("command")
                                or args.get("cmd")
                                or args.get("args")
                            )
                            return (
                                f"agent wants to execute shell command: {cmd}"
                                if cmd
                                else f"agent wants to execute {name}"
                            )
                        url = (
                            args.get("url")
                            or args.get("uri")
                            or args.get("link")
                        )
                        if url:
                            return f"agent wants to access external resources, path {url} (read file)"
                        arg_summary = ", ".join(
                            f"{k}={v}" for k, v in list(args.items())[:2]
                        )
                        return (
                            f"agent wants to run {name} with args: {arg_summary}"
                            if arg_summary
                            else f"agent wants to run {name}"
                        )

                    hitl = HitlRequest(
                        tool_call_id=call_id,
                        tool_name=name,
                        tool_args=args,
                        risk_class=risk,
                        allowed_decisions=("approve", "reject", "edit"),
                        reason=_hitl_reason(name, args),
                    )
                    self._persist_snapshot(
                        thread_id,
                        messages=messages,
                        step=steps,
                        tool_calls=tool_call_count,
                        pending_hitl=hitl,
                    )
                    yield HitlRequired(
                        call_id=call_id,
                        tool_name=name,
                        tool_args=args,
                        allowed_decisions=hitl.allowed_decisions,
                        reason=hitl.reason,
                    )
                    step_interrupted = True
                    break

                yield from self._execute_tool(call_id, name, args, messages)
                tool_call_count += 1

            if step_interrupted:
                return

            steps += 1
            yield StepEnd(step=steps)
            self._persist_snapshot(
                thread_id,
                messages=messages,
                step=steps,
                tool_calls=tool_call_count,
                pending_hitl=None,
            )

        yield RunError(
            thread_id=thread_id,
            error=f"max_steps ({self._max_steps}) exceeded",
            step=steps,
        )

    def _execute_tool(
        self,
        call_id: str,
        name: str,
        args: Mapping[str, Any],
        messages: list[dict[str, Any]],
    ) -> Iterator[Any]:
        """Dispatch a tool call and yield lifecycle events.

        Yields ``ToolStart`` on entry, then either ``ToolEnd`` (success)
        or ``ToolError`` (failure).  The final value yielded (via
        ``return``) is the tool's return value (``None`` on error).

        :param call_id: Unique ID for this tool call.
        :param name: Tool name.
        :param args: Tool arguments.
        :param messages: The current message list, to which the tool's
            result or error is appended.
        :return: Yields :class:`ToolStart`, then either :class:`ToolEnd`
            or :class:`ToolError`.  The final value is the tool's return
            value (``None`` on error).
        """
        spec = self._registry.get(name)
        if spec is None or spec.execute is None:
            err = f"unknown tool {name!r}"
            messages.append(_tool_error_message(call_id, name, err))
            return None

        yield ToolStart(call_id=call_id, tool_name=name, tool_args=args)
        start = time.monotonic()
        try:
            output = spec.execute(**args)
        except Exception as exc:  # ruff: ignore[blind-except]
            duration_ms = int((time.monotonic() - start) * 1000)
            err = f"{type(exc).__name__}: {exc}"
            messages.append(_tool_error_message(call_id, name, err))
            yield ToolError(call_id=call_id, tool_name=name, error=err)
            return None
        duration_ms = int((time.monotonic() - start) * 1000)
        messages.append(
            _tool_result_message(call_id, name, output),
        )
        yield ToolEnd(
            call_id=call_id,
            tool_name=name,
            output=output,
            duration_ms=duration_ms,
        )
        return output  # ruff: ignore[return-in-generator]

    def _step_start(self, step: int) -> StepStart:
        """Build a :class:`StepStart` and notify the callback.

        :param step: The current step number (0-based).
        :return: The :class:`StepStart` event.
        """
        evt = StepStart(step=step, max_steps=self._max_steps)
        if self._on_step is not None:
            self._on_step(evt)
        return evt

    def _is_cancelled(self, thread_id: str) -> bool:
        """Check if the given thread_id has been marked for cancellation.

        :param thread_id: The thread ID to check.
        :return: True if the thread is cancelled, False otherwise.
        """
        return thread_id in self._cancel_flags

    def _risk_for(self, tool_name: str) -> str:
        """Return the effective risk class for a tool, defaulting to "medium".

        :param tool_name: The name of the tool to check.
        :return: The effective risk class as a string.
        """
        spec = self._registry.get(tool_name)
        if spec is None:
            return "medium"
        return effective_risk_class(spec)

    def _openai_tools(self) -> list[dict[str, Any]]:
        """Return the tool registry as a list of OpenAI-shaped dicts.

        :return: A list of tool specifications in OpenAI format.
        """
        return [spec.to_openai_tool() for spec in self._registry.all()]

    def _persist_snapshot(
        self,
        thread_id: str,
        *,
        messages: list[dict[str, Any]],
        step: int,
        tool_calls: int,
        pending_hitl: HitlRequest | None,
    ) -> None:
        """Persist the current state of the loop for resuming later.

        :param thread_id: The thread ID for which to persist the snapshot.
        :param messages: The current list of messages.
        :param step: The current step number.
        :param tool_calls: The current count of tool calls made.
        :param pending_hitl: The current pending HITL request, if any.
        """
        if self._checkpointer is None:
            return
        # The checkpointer's ``pending_hitl`` slot is typed as a
        # ``Mapping``; serialise the dataclass to a dict so the
        # round-trip is shape-stable across processes.
        pending_dict: dict[str, Any] | None = (
            None if pending_hitl is None else asdict(pending_hitl)
        )
        snap = make_snapshot(
            thread_id=thread_id,
            messages=messages,
            step=step,
            tool_calls=tool_calls,
            pending_hitl=pending_dict,
        )
        self._checkpointer.put(thread_id, snap)

    def _load_snapshot(self, thread_id: str) -> Mapping[str, Any] | None:
        """Load a persisted snapshot for the given thread_id.

        :param thread_id: The thread ID for which to load the snapshot.
        :return: The snapshot as a mapping, or None if not found.
        """
        if self._checkpointer is None:
            return None
        snap = self._checkpointer.get(thread_id)
        if snap is None:
            return None
        # Re-hydrate the pending_hitl dict back into a HitlRequest so
        # downstream code (``is_valid_decision``) sees the dataclass
        # type it expects.
        pending = snap.get("pending_hitl")
        if isinstance(pending, Mapping) and pending:
            snap = dict(snap)
            snap["pending_hitl"] = HitlRequest(**pending)
        return snap


# ---------------------------------------------------------------------------
# Adapter-response parsing helpers
# ---------------------------------------------------------------------------


def _extract_assistant_message(response: Any) -> dict[str, Any]:
    """Pull the first assistant choice out of an OpenAI-shaped dict.

    :param response: The raw response from the adapter.
    :return: The assistant message as a dict.
    """
    if not isinstance(response, Mapping):
        raise TypeError(
            f"adapter response must be a Mapping, got {type(response).__name__}",
        )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("adapter response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise TypeError("adapter response choice is not a Mapping")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise TypeError("adapter response choice has no message Mapping")
    return dict(message)


def _extract_tool_calls(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the message's tool_calls as a list of ``{id, name, args}`` dicts.

    Handles three shapes:

    1. OpenAI shape: ``message["tool_calls"]`` is a list of
       ``{"id", "type": "function", "function": {"name", "arguments"}}``.
    2. Anthropic shape: ``message["content"]`` is a list of blocks
       with ``type == "tool_use"``.  (Not emitted by the current
       :class:`NativeAdapter`, but we accept it so the loop is
       provider-agnostic.)
    3. Empty / no tool calls: return ``[]``.

    :param message: The assistant message dict.
    :return: A list of tool call dicts, each with ``id``, ``name``, and ``args`` keys.
    :raises TypeError: if the message is not a mapping or has unexpected structure.
    :raises ValueError: if the message has no tool calls and no content blocks.
    :return: A list of tool call dicts, each with ``id``, ``name``, and ``args`` keys.
    """
    out: list[dict[str, Any]] = []
    raw = message.get("tool_calls")
    if isinstance(raw, list):
        for tc in raw:
            if not isinstance(tc, Mapping):
                continue
            call_id = str(tc.get("id") or uuid.uuid4())
            fn = tc.get("function")
            if not isinstance(fn, Mapping):
                continue
            name = str(fn.get("name") or "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                # Some providers serialise arguments as a JSON string.
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if not isinstance(args, Mapping):
                args = {}
            out.append({"id": call_id, "name": name, "args": dict(args)})
        return out

    # Anthropic fallback
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "tool_use":
                out.append(
                    {
                        "id": str(block.get("id") or uuid.uuid4()),
                        "name": str(block.get("name") or ""),
                        "args": dict(block.get("input") or {})},
                )
    return out


def _tool_result_message(
    call_id: str,
    name: str,
    output: Any,
) -> dict[str, Any]:
    """Build a ``tool`` role message that feeds the result back to the model.

    :param call_id: The tool call ID.
    :param name: The tool name.
    :param output: The tool's output, which will be coerced to a string.
    :return: A dict representing the message.
    """
    if not isinstance(output, str):
        output = repr(output)
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "name": name,
        "content": output}


def _tool_error_message(
    call_id: str,
    name: str,
    error: str,
) -> dict[str, Any]:
    """Same as :func:`_tool_result_message` but for an error string.

    :param call_id: The tool call ID.
    :param name: The tool name.
    :param error: The error message.
    :return: A dict representing the message.
    """
    return _tool_result_message(call_id, name, f"ERROR: {error}")


__all__ = [
    "BergLoop",
    "ContentDelta",
    "HitlRequired",
    "HitlResolved",
    "LoopEvent",
    "MessageFinish",
    "RunCancelled",
    "RunCompleted",
    "RunError",
    "RunStarted",
    "StepCallback",
    "StepEnd",
    "StepStart",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolEnd",
    "ToolError",
    "ToolStart"]
