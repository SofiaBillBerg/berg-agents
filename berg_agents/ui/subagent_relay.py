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

"""Relay a subagent's streamed run into the parent run's journal.

The staged delegates (``implement_task``) run their own agent - a second
pydantic-ai graph inside the parent's tool call. That graph's events never
reach the parent's encoder, so before this module the web UI showed
"Thinking…" for the whole subagent run and the only channel out was one
short line per tool call: enough to see *that* the implementer worked,
never *what* it did.

The relay gives each subagent run its own ``VercelAIEventStream`` and
journals its frames into the parent's SSE journal, so the implementer's
text, reasoning and tool calls stream live into the same assistant
message, directly under the ``implement_task`` card.

Two protocol rules shape it, because those frames land inside a stream the
parent's encoder is still writing:

* Turn boundaries belong to the parent. A second ``start``, ``finish`` or
  ``done`` mid-stream would make the client open a second message or stop
  reading, so only content chunks pass through.
* Approval identity belongs to the parent. A ``tool-approval-request``
  names an approval the run registry cannot resolve - answering one would
  be applied to a run that never asked - so it is dropped here and the
  tool body reports a subagent that paused as visible text instead.

The trade is stated plainly: a subagent's parts exist on the wire only. A
transcript is rebuilt from the parent run's own ``all_messages()``, which
records the parent's messages and not the child's, so once the turn ends
the nested activity is no longer rendered. What the run *recorded* -
files changed, steps checked off - survives, because that is the parent's
own history.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Chunk type carrying a subagent stream's bracket. The client groups the
#: parts arriving between a ``start`` and its matching ``end`` under the
#: parent tool call the bracket names.
SUBAGENT_MARKER_TYPE = "data-subagent"


@cache
def _content_chunk_types() -> tuple[type, ...]:
    """Chunk types the relay passes through, resolved once on first use.

    An allowlist rather than a denylist on purpose: the parent's stream is
    live while these frames land in it, so an unlisted chunk must never be
    able to open a message, close one, or end the stream. A chunk type a
    future pydantic-ai adds is therefore dropped with a warning instead of
    being assumed harmless.

    :return: Tuple of chunk classes that render as content inside an
        already-open message.
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


@cache
def _failure_chunk_types() -> tuple[type, ...]:
    """Chunk types that report the subagent's own run ending badly.

    :return: Tuple of chunk classes carrying an error or abort report.
    """
    from pydantic_ai.ui.vercel_ai.response_types import AbortChunk, ErrorChunk

    return (ErrorChunk, AbortChunk)


class SubagentRelay:
    """Carry one subagent's streamed run into the parent run's journal.

    One relay serves a whole parent turn, so a delegate called twice (two
    ``implement_task`` calls in one turn) streams both runs through the
    same channel; every :meth:`drive` call builds its own encoder, because
    one encoder's turn bookkeeping belongs to one run.

    :param append: Journals one encoded SSE frame - the parent run's own
        append. Called from the task that drives the parent graph, the
        same place the parent's per-node frames are journalled from, so
        relayed frames keep event order.
    :param note: Journals one plain visible line - the parent run's text
        notice. Used for what is *about* the subagent run rather than part
        of its stream: a pause, or a stream that died.
    :param sdk_version: Vercel AI protocol version to encode with - the
        parent's, so a relayed chunk has the shape a parent chunk has.
    """

    def __init__(
        self,
        *,
        append: Callable[[str], None],
        note: Callable[[str], None],
        sdk_version: int,
    ) -> None:
        """Store the parent run's two journal channels and the protocol version.

        :param append: Frame journaling callback of the parent run.
        :param note: Plain-line journaling callback of the parent run.
        :param sdk_version: Protocol version the parent's encoder uses.
        """
        self._append = append
        self._note = note
        self._sdk_version = sdk_version

    def note(self, text: str) -> None:
        """Journal one plain line above the subagent's streamed parts.

        :param text: Line to show. Blank text is dropped rather than
            journalled as an empty paragraph.
        """
        if text.strip():
            self._note(text.strip())

    def start(self, parent_tool_call_id: str) -> None:
        """Announce that a subagent's stream begins, and whose it is.

        The bracket is what lets the UI nest the subagent's parts under
        the parent tool call: the client keeps these data parts on the
        assistant message and groups what arrives between them. Without
        it the parts still stream, but they land as loose siblings of
        the ``implement_task`` card rather than inside it.

        :param parent_tool_call_id: The parent tool call the subagent
            belongs to (``implement_task``'s own call id).
        """
        if not parent_tool_call_id:
            return
        self._emit_data(
            "data-subagent",
            {"phase": "start", "parentToolCallId": parent_tool_call_id},
        )

    def end(self, parent_tool_call_id: str) -> None:
        """Announce that a subagent's stream has finished.

        :param parent_tool_call_id: The parent tool call, matching the
            :meth:`start` bracket.
        """
        if not parent_tool_call_id:
            return
        self._emit_data(
            "data-subagent",
            {"phase": "end", "parentToolCallId": parent_tool_call_id},
        )

    def _emit_data(self, kind: str, data: dict[str, Any]) -> None:
        """Journal one data-carrying protocol chunk.

        :param kind: Chunk type; must start with ``data-`` for the client
            to keep it on the assistant message.
        :param data: The payload the client reads.
        """
        from pydantic_ai.ui.vercel_ai.response_types import DataChunk

        chunk = DataChunk(type=kind, data=data)
        self._append(f"data: {chunk.encode(self._sdk_version)}\n\n")

    async def drive(self, _sub_ctx: Any, event_stream: Any) -> None:
        """Stream one subagent run's events into the parent's journal.

        This is the body of an ``event_stream_handler``: pydantic-ai awaits
        it inline with each node's stream, so the subagent's events arrive
        here in run order and no second task is needed to keep up with
        them. Iterating to the end of the stream is what lets the child's
        own stream wrappers finalize, so the loop never breaks early.

        :param _sub_ctx: The subagent's run context (unused - the relay
            only carries events, never drives the child's graph).
        :param event_stream: The subagent's native event stream.
        """
        # The same cap the parent's turn stream uses, so one oversized
        # tool result cannot bloat the journal whichever graph produced it.
        from berg_agents.ui.route_handlers.chat import cap_tool_results
        from pydantic_ai.ui.vercel_ai import VercelAIEventStream

        encoder = VercelAIEventStream(sdk_version=self._sdk_version)
        try:
            async for chunk in encoder.transform_stream(
                cap_tool_results(event_stream)
            ):
                self._journal(encoder, chunk)
        except Exception as exc:  # the child's stream died under the encoder
            # The library turns a dead child stream into its own error
            # chunk, which _journal drops; this branch covers the encoder
            # itself failing. Either way the subagent's run raises inside
            # the tool body, so the parent's encoder reports the turn's
            # failure - this line only records where it happened.
            logger.warning("subagent relay failed: %s", exc)
            self.note(f"⚠️ Subagent stream failed: {str(exc)[:300]}")

    def _journal(self, encoder: Any, chunk: Any) -> None:
        """Journal one protocol chunk, keeping only what the parent allows.

        :param encoder: The subagent run's encoder, which serializes the
            chunk with the protocol version it was built for.
        :param chunk: One protocol chunk from the subagent's stream.
        """
        if isinstance(chunk, _content_chunk_types()):
            self._append(encoder.encode_event(chunk))
            return
        if isinstance(chunk, _failure_chunk_types()):
            # The child stream ended in an error or an abort. The chunk
            # itself must not reach the parent's wire - a client that
            # reads `error` mid-message stops rendering that message - so
            # the failure travels as a visible line instead.
            detail = str(
                getattr(chunk, "error_text", None)
                or getattr(chunk, "reason", None)
                or chunk
            )
            self.note(f"⚠️ Subagent stopped: {detail[:300]}")
            return
        # Turn control (`start`, step boundaries, `finish`, `done`, message
        # metadata) and approval requests: the parent's encoder owns every
        # one of those, and a second copy on the wire would corrupt the
        # turn the parent is still writing.
        logger.debug("subagent relay dropped %s", type(chunk).__name__)
