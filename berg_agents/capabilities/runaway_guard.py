# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Runaway guard - two-stage check-in for a long unstoppered run.

A session here runs for weeks and is resumable, so there is no per-run
budget: nothing should end a turn with an error because a conversation is old.
What a collaborative session does need is a guarantee that the agent cannot
work indefinitely without the human getting a say.

Stage one (soft, at ``limit`` tool calls) adds a fixed advisory system prompt
to the next model request: the agent is told how long it has been working
unattended and asked to check in. It costs no extra model call and it leaves
the wording of the check-in to the model (reply, or call ``ask_user``).

Stage two (hard, at ``2 * limit``) raises
:class:`~pydantic_ai.exceptions.ApprovalRequired` from
``before_tool_execute``, so the next call becomes a deferred approval and the
run pauses until the human answers. That cannot be ignored, which is what
stage one deliberately can.

The count is per session and lives in the session store
(:func:`berg_agents.ui.session_store.read_guard_progress`), because the agent
object is rebuilt per request. A message the user sends while the agent is
working does not reset it; only the agent yielding control does.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities import AbstractCapability

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.messages import ModelRequestContext
    from pydantic_ai.tools import ToolDefinition

logger = logging.getLogger(__name__)

#: Fixed advisory sent when the run crosses the soft threshold. Deliberately
#: static: generating the text would cost the extra model call the check-in
#: exists to avoid.
_CHECK_IN_REMINDER = (
    "You have now made {count} tool calls in this session without the user "
    "stepping in. This is a collaboration, not an unattended job: pause and "
    "tell the user what you have found so far and what you are about to do. "
    "If the direction is uncertain, ask them. If they are not there, stop and "
    "wait - do not keep working alone."
)


class RunawayGuard(AbstractCapability[Any]):
    """Ask the agent to check in, then force a pause if it does not.

    :param limit: Tool calls allowed without human intervention before the
        advisory reminder fires. The hard pause follows at ``2 * limit``.
    :param session_id: Session whose counter is tracked; ``None`` disables the
        capability for this run (there is nowhere to persist the count).
    """

    def __init__(self, *, limit: int, session_id: str | None) -> None:
        """Store the configured limit and the session to track."""
        super().__init__()
        self.limit = max(1, int(limit))
        self.session_id = session_id

    async def before_model_request(
        self, ctx: RunContext[Any], request_context: ModelRequestContext
    ) -> ModelRequestContext:
        """Fire the advisory reminder once per stretch, at the soft threshold.

        Request-scoped (``SystemPromptPart`` enqueued for this request only),
        so it adds recency without accumulating copies in the history.
        """
        if not self.session_id:
            return request_context
        from berg_agents.ui import session_store
        from pydantic_ai.messages import SystemPromptPart

        count, nudged = session_store.read_guard_progress(self.session_id)
        if nudged or count < self.limit:
            return request_context
        ctx.enqueue(
            SystemPromptPart(
                _CHECK_IN_REMINDER.format(count=count),
                # The reminder is a nudge for the next step only; keeping it
                # for the rest of the conversation would re-assert "you have
                # made N calls" long after the count changed.
                scope="request",
                # Origin metadata so the reminder is identifiable in history
                # rather than by matching its text.
                metadata={"origin": "berg-agents.runaway-guard.nudge.v1"},
            )
        )
        session_store.write_guard_progress(
            self.session_id, tool_calls=count, nudged=True
        )
        logger.info(
            "Runaway guard: check-in reminder after %s tool calls (session %s)",
            count,
            self.session_id,
        )
        return request_context

    async def before_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: Any,
        tool_def: ToolDefinition,
        args: Any,
    ) -> Any:
        """Count the call, and force a pause once the hard threshold is reached.

        Counting happens here rather than after execution so a tool that
        fails still counts towards "has been working unattended": the point
        is the human's absence, not the tool's success.

        :raises ApprovalRequired: At ``2 * limit`` calls, deferring this call
            so the run pauses for the human through the approval batch.
        """
        if not self.session_id:
            return args
        from berg_agents.ui import session_store
        from pydantic_ai.exceptions import ApprovalRequired

        count, nudged = session_store.read_guard_progress(self.session_id)
        count += 1
        if count >= self.limit * 2:
            session_store.write_guard_progress(
                self.session_id, tool_calls=count, nudged=nudged
            )
            logger.warning(
                "Runaway guard: pausing after %s unattended tool calls "
                "(session %s, tool %s)",
                count,
                self.session_id,
                tool_def.name,
            )
            raise ApprovalRequired(
                metadata={
                    "origin": "berg-agents.runaway-guard.pause.v1",
                    "reason": (
                        f"{count} tool calls without the user stepping in - "
                        "the agent must check in before continuing."
                    )}
            )
        session_store.write_guard_progress(
            self.session_id, tool_calls=count, nudged=nudged
        )
        return args


__all__ = ["RunawayGuard"]
