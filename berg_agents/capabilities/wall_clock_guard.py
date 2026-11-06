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

"""Wall-clock guard - a run that has gone on too long asks the user.

A session here runs for weeks and is resumable, so there is no per-run
budget in the sense of "this turn may take N minutes and then it dies".
What a collaborative session does need is a guarantee that a run cannot keep
working for an unbounded stretch of wall-clock time without the user getting
a say - a slow model, a provider that never answers, a tool that waits.

The pause is raised from ``before_tool_execute`` as
:class:`~pydantic_ai.exceptions.ApprovalRequired`, exactly like the runaway
guard's hard stop, so the protocol already knows how to render it: the next
tool call becomes a deferred approval and the run pauses on a real approval
card. That is the whole point - the user answers the same card they answer
for every other gated action, and an approved "continue" simply lets the call
run. The deadline is then re-armed from that answer, so approving means "the
next stretch of work", not "forever".

The deadline is per run, armed in ``before_run``. It deliberately does not
count time the run spent paused: the run is not executing while it waits for
a user, and a pause that expired the limit would fire the instant the user
answered.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities import AbstractCapability

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.tools import ToolDefinition

logger = logging.getLogger(__name__)


class WallClockGuard(AbstractCapability[Any]):
    """Pause a run for approval once it has been executing too long.

    :param limit_seconds: How long a run may keep working before the next tool
        call is deferred for a user decision. ``0`` or less disables the
        guard.
    """

    def __init__(self, *, limit_seconds: float) -> None:
        """Store the limit and start with no deadline armed.

        :param limit_seconds: Wall-clock ceiling for one stretch of work.
        """
        super().__init__()
        self.limit_seconds = float(limit_seconds)
        #: Monotonic time the current stretch began. ``None`` until the run
        #: starts (and again after the user has answered a pause).
        self._stretch_started: float | None = None

    async def before_run(self, ctx: RunContext[Any]) -> None:
        """Start the clock for this run.

        Observe-only hook (the base contract): it records when the stretch
        began so the first tool call can compare against it.
        """
        _ = ctx
        self._stretch_started = (
            time.monotonic() if self.limit_seconds > 0 else None
        )

    async def before_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: Any,
        tool_def: ToolDefinition,
        args: Any,
    ) -> Any:
        """Defer this call if the run has outlived its wall-clock limit.

        Deferring here is the documented place for it: a tool call may only be
        deferred once its arguments are validated, and deferring before the
        body runs means nothing has been executed yet.

        :raises ApprovalRequired: When the current stretch has run past
            ``limit_seconds``; the call pauses on an approval card instead of
            executing.
        """
        _ = ctx
        started = self._stretch_started
        if started is None:
            return args
        elapsed = time.monotonic() - started
        if elapsed < self.limit_seconds:
            return args

        from pydantic_ai.exceptions import ApprovalRequired

        # Restart the clock before raising: if the user approves, the tool
        # runs and the run gets a fresh stretch. Without this the next call
        # would trip the same expired limit and the pause would repeat
        # forever.
        self._stretch_started = time.monotonic()
        logger.warning(
            "Wall-clock guard: pausing %s after %.0f minutes (limit %.0f "
            "minutes)",
            tool_def.name,
            elapsed / 60,
            self.limit_seconds / 60,
        )
        raise ApprovalRequired(
            metadata={
                "origin": "berg-agents.wall-clock-guard.pause.v1",
                "reason": (
                    f"This run has been working for {elapsed / 60:.0f} "
                    f"minutes (limit {self.limit_seconds / 60:.0f}). "
                    "Approve to continue, or reject and tell me how to "
                    "proceed."
                )}
        )


__all__ = ["WallClockGuard"]
