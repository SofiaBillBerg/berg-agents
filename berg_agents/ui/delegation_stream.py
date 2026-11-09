# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

"""Carry a delegated sub-agent's own run into the parent turn's wire.

The harness's ``SubAgents`` + ``TaskControl`` capability runs a delegated
task as a first-class thing, and everything a delegated task does arrives
on the *parent's* event stream: the task's lifecycle
(``TaskAssignedEvent``/``TaskStartedEvent`` … ``TaskCompletedEvent``), the
child's own native events one at a time (``TaskProgressEvent``), and its
question (``TaskQuestionEvent``). With ``forward_events=True`` the child's
whole stream is in there - verified as ``PartStartEvent``,
``PartEndEvent``, ``FunctionToolCallEvent``, ``FunctionToolResultEvent``
and ``FinalResultEvent``, one ``TaskProgressEvent`` each.

``VercelAIEventStream.handle_event`` is a ``match`` statement with no
default branch, so those events fall through it silently: the encoder does
not raise, it simply emits nothing, and a delegated run shows an empty
``delegate_task`` card. That is why "the encoder accepts these events"
proved nothing - accepting and emitting are different things. This module
is the missing arm of that match.

Two protocol rules shape what may pass through, because these frames land
inside the stream the parent's encoder is still writing. They were earned
by the relay that carried a sub-agent's stream before this module existed
(``berg_agents.ui.subagent_relay``, retired with the staged delegate it
served), and they are the relay's one surviving contribution:

* Turn boundaries belong to the parent. A second ``start``, ``finish``
  or ``done`` mid-stream would make the client open a second message or
  stop reading, so only the child's content chunks pass through.
* Approval identity belongs to the parent. A ``tool-approval-request``
  names an approval the run registry cannot resolve, so it is dropped.

Unlike the relay, no child encoder's state is borrowed across runs: each
task gets its own encoder, created on that task's first progress event,
because one encoder's ``_open_part`` and ``_final_result_event`` state
belongs to one run. Driving a child's events through the parent's own
encoder would let its ``FinalResultEvent`` overwrite the parent's - the
event the error path falls back on when a turn dies before ``End``.

Which events bracket a task depends on the path the delegation took,
because the two paths report a task's start differently:

* **Task control** (the owner is bound): ``owner.publish`` puts the task
  events on the run's stream - ``TaskAssignedEvent`` opens, the settled
  event closes - while the delegation's own start/end go to
  ``owner.notify``, which reaches observers only and never the stream.
* **Plain** (no owner): ``ctx.emit`` puts ``DelegationStartEvent`` and
  ``DelegationEndEvent`` on the stream, with no task events at all.

Both pairs are therefore read, and only one bracket is ever open: on the
task-control path the delegation events are simply absent, and on the
plain path the task events are.

Known limit: the bracket names the tool call on top of the delegation
stack. Sequential and nested delegations are exact; two delegates in one
step (parallel tool execution) would both bracket against whichever call
opened last, which is a ceiling of the ``sub_agents`` events - they
carry a task id, not the parent call id that opened them.
"""

from __future__ import annotations

import logging
from typing import Any
import uuid

logger = logging.getLogger(__name__)

#: Chunk type naming a delegated sub-agent's stream bracket. The client's
#: ``messageParts.ts`` already knows this exact shape: it attaches the
#: parts arriving between a start and an end to the tool call the bracket
#: names, which renders them inside that call's card.
DELEGATION_CHUNK_TYPE = "data-subagent"

#: The bracket's extra key. The client groups the streamed parts by
#: ``parentToolCallId`` and ignores the rest, so this is additive: a task
#: id the client does not yet read costs nothing, and it is the only
#: handle a steer or a stop has on a live task.
DELEGATION_TASK_ID_KEY = "taskId"

#: Chunk type naming a delegated task's question. Phase 2c turns this
#: into an answerable card; today it records that a task is waiting
#: rather than letting the journal show a silent stall.
DELEGATION_QUESTION_CHUNK_TYPE = "data-delegation-question"

#: The tool name whose calls are delegation brackets.
DELEGATE_TOOL_NAME = "delegate_task"

#: Task events that open a delegated task's stream.
_TASK_OPEN_EVENTS = ("TaskAssignedEvent", "TaskStartedEvent")

#: Task events that close it. A task that ends badly still closes its
#: bracket, otherwise the client would nest every later part forever.
_TASK_SETTLED_EVENTS = (
    "TaskCompletedEvent",
    "TaskFailedEvent",
    "TaskCancelledEvent",
)


def _content_chunk_types() -> tuple[type, ...]:
    """Protocol chunks that carry a sub-agent's own content.

    Everything else a child encoder produces describes the parent's turn
    (``start``, ``start-step``, ``finish-step``, ``finish``,
    ``message-metadata``) or an approval the run registry cannot resolve
    (``tool-approval-request``).

    :return: Tuple of chunk classes allowed to reach the client.
    """
    from pydantic_ai.ui.vercel_ai.response_types import (
        DataChunk,
        FileChunk,
        ReasoningDeltaChunk,
        ReasoningEndChunk,
        ReasoningStartChunk,
        SourceUrlChunk,
        TextDeltaChunk,
        TextEndChunk,
        TextStartChunk,
        ToolInputAvailableChunk,
        ToolInputDeltaChunk,
        ToolInputErrorChunk,
        ToolInputStartChunk,
        ToolOutputAvailableChunk,
        ToolOutputDeniedChunk,
        ToolOutputErrorChunk,
    )

    return (
        TextStartChunk,
        TextDeltaChunk,
        TextEndChunk,
        ReasoningStartChunk,
        ReasoningDeltaChunk,
        ReasoningEndChunk,
        ToolInputStartChunk,
        ToolInputDeltaChunk,
        ToolInputAvailableChunk,
        ToolInputErrorChunk,
        ToolOutputAvailableChunk,
        ToolOutputErrorChunk,
        ToolOutputDeniedChunk,
        FileChunk,
        SourceUrlChunk,
        DataChunk,
    )


def _subagent_api() -> dict[str, Any]:
    """The harness's ``sub_agents`` classes, by the role they play here.

    Imported once per build rather than per event: this runs for every
    event of every turn, and the import is a dict lookup but the tuple
    building is not.

    :return: Mapping of role to the event class (or None when a role's
        class does not exist in the installed harness).
    """
    from pydantic_ai_harness import subagents as harness

    def cls(name: str) -> Any:
        return getattr(harness, name, None)

    return {
        "delegation_start": cls("DelegationStartEvent"),
        "delegation_end": cls("DelegationEndEvent"),
        "task_assigned": cls("TaskAssignedEvent"),
        "task_started": cls("TaskStartedEvent"),
        "task_completed": cls("TaskCompletedEvent"),
        "task_failed": cls("TaskFailedEvent"),
        "task_cancelled": cls("TaskCancelledEvent"),
        "task_progress": cls("TaskProgressEvent"),
        "task_question": cls("TaskQuestionEvent")}


def build_delegation_event_stream(sdk_version: int = 6) -> Any:  # ruff: ignore[complex-structure]
    """Build the encoder that also carries a delegated sub-agent's run.

    The subclass is defined here rather than at module level so the
    harness's event classes can be closed over, and so a harness that is
    not installed degrades to the plain encoder instead of failing this
    module's import - which would take the chat route with it. The
    structural complexity is that closure, not branching.

    With the harness absent there is nothing to translate, so the plain
    library encoder is returned and this module costs one ``isinstance``
    that never matches.

    :param sdk_version: Vercel AI protocol version to encode with - the
        parent's, so a relayed chunk has the shape a parent chunk has.
    :return: A ``VercelAIEventStream`` (possibly the delegation-aware
        subclass), ready to drive the turn.
    """
    from pydantic_ai.messages import ToolCallEvent, ToolResultEvent
    from pydantic_ai.ui.vercel_ai import VercelAIEventStream

    events = _subagent_api()
    if not any(events.values()):  # pragma: no cover - older harness
        logger.warning(
            "delegated runs will not stream their own work: "
            "no sub_agents events in the installed harness"
        )
        return VercelAIEventStream(sdk_version=sdk_version)

    class DelegationEventStream(VercelAIEventStream):
        """The parent's own encoder, extended to read ``sub_agents`` events.

        It is a subclass rather than a wrapper because ``handle_event``
        is the documented per-event hook, and the parent's encoder must
        keep owning the turn: message identities, step boundaries, the
        approval surface and the final result all stay where the protocol
        put them.
        """

        def __init__(self) -> None:
            """Start with an empty delegation stack and no child encoders."""
            super().__init__(sdk_version=sdk_version)
            # Call ids of the delegate_task calls currently streaming,
            # innermost last. Pushed when the model emits the call and
            # popped when its result arrives, so a bracket names the call
            # whose task it belongs to.
            self._delegating_calls: list[str] = []
            # One encoder per task id, because a child's _open_part and
            # _final_result_event state belongs to one run.
            self._child_encoders: dict[str, Any] = {}
            # Whether a bracket is open. Only one is ever open, so a
            # stray event cannot nest a second bracket inside the first.
            self._bracket_open = False

        async def handle_event(self, event: Any) -> Any:
            """Translate one native event, ``sub_agents`` events included.

            :param event: One pydantic-ai native event.
            :return: Async iterator of protocol chunks.
            """
            # Tracked first: the bracket that names a call is emitted
            # after the call's own event has already gone past.
            self._track_delegating_call(event)

            task_open = self._is_a(event, "task_assigned", "task_started")
            task_settled = self._is_a(
                event, "task_completed", "task_failed", "task_cancelled"
            )
            opens = self._is_a(event, "delegation_start") or task_open
            closes = self._is_a(event, "delegation_end") or task_settled
            if opens or closes:
                phase = "start" if opens else "end"
                bracket = self._bracket_chunk(phase, event)
                # None means this bracket is a duplicate of one already
                # open or already closed, so it must not reach the wire.
                if bracket is not None:
                    yield bracket
                return
            if self._is_a(event, "task_question"):
                # The question is not yet an answerable protocol question
                # (phase 2c); this carries the task id and the text so the
                # card can be built, and so the journal records that a
                # task is waiting instead of showing a silent stall.
                from pydantic_ai.ui.vercel_ai.response_types import DataChunk

                yield DataChunk(
                    type=DELEGATION_QUESTION_CHUNK_TYPE,
                    data={
                        "taskId": str(getattr(event, "task_id", "") or ""),
                        "agentName": str(
                            getattr(event, "agent_name", "") or ""
                        ),
                        "question": str(getattr(event, "question", "") or "")},
                )
                return
            if self._is_a(event, "task_progress"):
                async for chunk in self._handle_progress(event):
                    yield chunk
                return

            # Everything else is the parent's own event: the base encoder
            # keeps it, turn boundaries and all.
            async for chunk in super().handle_event(event):
                yield chunk

        @staticmethod
        def _is_a(event: Any, *roles: str) -> bool:
            """Whether an event is one of the ``sub_agents`` classes.

            Missing classes (an older harness) never match, so each role
            degrades to "this path does not happen here" rather than
            erroring.

            :param event: One native event.
            :param roles: Roles from :func:`_subagent_api` to test.
            :return: True when the event is any of them.
            """
            wanted = [events[role] for role in roles]
            wanted = [cls for cls in wanted if cls is not None]
            if not wanted:
                return False
            return isinstance(event, tuple(wanted))

        def _track_delegating_call(self, event: Any) -> None:
            """Keep the stack of delegate_task calls currently streaming.

            The bracket a delegation emits must name the call that opened
            it, and that call's own event arrives one event earlier in the
            same node stream - so it is recorded here, on the way through.

            :param event: One native event, possibly a delegate call or
                its result.
            """
            if isinstance(event, ToolCallEvent):
                part = getattr(event, "part", None)
                name = str(getattr(part, "tool_name", "") or "")
                if name == DELEGATE_TOOL_NAME:
                    call_id = str(getattr(part, "tool_call_id", "") or "")
                    if call_id:
                        self._delegating_calls.append(call_id)
            elif isinstance(event, ToolResultEvent):
                part = getattr(event, "part", None)
                name = str(getattr(part, "tool_name", "") or "")
                if name == DELEGATE_TOOL_NAME and self._delegating_calls:
                    # Remove the specific call when it can be named, else
                    # the innermost one: a result must always unwind the
                    # stack, or every later bracket names a dead call.
                    call_id = str(getattr(part, "tool_call_id", "") or "")
                    if call_id in self._delegating_calls:
                        self._delegating_calls.remove(call_id)
                    else:
                        self._delegating_calls.pop()

        def _bracket_chunk(self, phase: str, event: Any) -> Any:
            """Build one bracket chunk for a delegation's stream.

            The shape is the one ``messageParts.ts`` already reads: a
            ``data-subagent`` part whose ``parentToolCallId`` names the
            tool call the subagent's parts belong to. An empty id
            brackets nothing, because there is no call to attribute the
            work to - and an idless bracket once crashed the render.

            A bracket that is already open is not opened twice: the two
            event pairs a delegation can report through are mutually
            exclusive on the wire, but a second open would nest every
            later part one level deeper than the client can render.

            :param phase: ``"start"`` or ``"end"``.
            :param event: The event supplying the agent name.
            :return: The protocol chunk, or ``None`` when one is dropped.
            """
            from pydantic_ai.ui.vercel_ai.response_types import DataChunk

            if phase == "start":
                if self._bracket_open:
                    return None
                self._bracket_open = True
            else:
                if not self._bracket_open:
                    return None
                self._bracket_open = False

            # A unique id per bracket. Without one the client's data-part
            # matching compares `id === id` with both undefined and the
            # SECOND bracket UPDATES the first instead of appending - the
            # open and close markers collapse into one, no bracket remains
            # open, and the child's parts stop being grouped under the call.
            # Verified from the client side: a message that held both
            # brackets while streaming lost the second on rebuild.
            return DataChunk(
                id=uuid.uuid4().hex,
                type=DELEGATION_CHUNK_TYPE,
                data={
                    "phase": phase,
                    "parentToolCallId": (
                        self._delegating_calls[-1]
                        if self._delegating_calls
                        else ""
                    ),
                    "agentName": str(getattr(event, "agent_name", "") or ""),
                    # Present on the opening bracket, which is where the
                    # task id first exists. Empty on the close, because a
                    # settled task has no id worth steering any more.
                    DELEGATION_TASK_ID_KEY: (
                        str(getattr(event, "task_id", "") or "")
                        if phase == "start"
                        else ""
                    )},
            )

        async def _handle_progress(self, event: Any) -> Any:
            """Stream one of the delegated child's own events.

            The child's native event is unwrapped and driven through that
            task's own encoder, so its text, reasoning and tool calls
            reach the client without touching the parent's turn state.

            :param event: The ``TaskProgressEvent`` carrying one child
                event.
            :return: Async iterator of the child's content chunks.
            """
            inner = getattr(event, "event", None)
            if inner is None:
                return
            task_id = str(getattr(event, "task_id", "") or "")
            encoder = self._child_encoders.get(task_id)
            if encoder is None:
                encoder = VercelAIEventStream(sdk_version=sdk_version)
                self._child_encoders[task_id] = encoder
            allowed = _content_chunk_types()
            async for chunk in encoder.handle_event(inner):
                if isinstance(chunk, allowed):
                    yield chunk

    return DelegationEventStream()
