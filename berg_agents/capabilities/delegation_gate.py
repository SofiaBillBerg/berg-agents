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

"""Ask the user before a delegated task starts.

A delegated implementer has ungated write tools: ``write_file``,
``edit_file`` and ``patch_file`` are plain functions, so a task that
misreads its plan can write with nothing in the way. Gating the
delegation itself - rather than the child's individual writes - is the
gate the staged ``implement_task`` carried (it was registered with
``requires_approval=True``), and it is the one this capability keeps.

Why this shape rather than the harness's ``TaskAssignedEvent`` veto: a
veto is a listener's synchronous reply, so the run would have to block
inside the tool call with no protocol surface to resume it. Deferring
the *tool call* instead is the documented place, and it means the user
answers the one card they already answer for every other gated action -
:class:`~berg_agents.capabilities.wall_clock_guard.WallClockGuard`
raises the same exception for the same reason. Approving resumes straight
into the delegation, so nothing is reimplemented on the way through.

The gate is deliberately one way to fail: it can only *ask*. A denial
returns the call to the model as a normal tool result, which is exactly
what the user's rejection means - "not like that" - and the model can
then re-delegate differently or stop.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_ai.capabilities import AbstractCapability

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.tools import ToolDefinition

logger = logging.getLogger(__name__)

#: The tool this capability gates. A delegation is a task, so the gate is
#: on the delegate call and not on anything the child does afterwards.
DELEGATE_TOOL_NAME = "delegate_task"

#: Metadata origin the approval card's respondent reads, so a delegated
#: task's approval is never mistaken for another kind of gate.
ORIGIN = "berg-agents.delegation-gate.approve.v1"

#: How much of the task text the card shows. A plan handed to a delegate
#: can be long; the card says what is being approved, not the whole brief.
_MAX_TASK_CHARS = 400

#: Call ids this process has deferred for approval and that have not yet
#: run. A resumed run re-executes the very same call and the hook fires on
#: it again, so an id in here means "this one is already waiting for the
#: user" - not "ask again". Without it the gate pauses forever: approve,
#: the call resumes, the hook fires, and the card asks again.
#:
#: Process-level rather than per-instance, because an agent is rebuilt per
#: run (``_session_agent``'s fingerprint), so the capability object that
#: paused a call is NOT the object the resumed run calls into - instance
#: state is empty by then. Verified: both hook invocations carried the
#: same ``tool_call_id`` while an instance-level set was empty on the
#: second.
#:
#: An id leaves the moment its call actually runs, so this holds only the
#: delegations waiting at once. The cap is the backstop for a run that
#: dies while paused, whose id would otherwise linger for the process's
#: life.
_MAX_PENDING_APPROVALS = 256
_pending_approvals: list[str] = []


class DelegationApprovalGate(AbstractCapability[Any]):
    """Ask the user to approve a delegation before the task starts.

    One capability, one rule: the model's ``delegate_task`` call pauses on
    an approval card until the user answers. Everything else runs
    untouched, so reads, searches and the task-control tools are never
    gated.

    :param enabled: When False the gate is inert - a delegation that needs
        no approval (a read-only task, or a session whose user has turned
        gating off) runs without a card.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        """Store whether the gate asks.

        :param enabled: Whether delegations pause for approval.
        """
        super().__init__()
        self.enabled = enabled

    async def before_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: Any,
        tool_def: ToolDefinition,
        args: Any,
    ) -> Any:
        """Defer the delegation until the user approves it.

        Deferring here is the documented place for it: a call may only be
        deferred once its arguments are validated, and deferring before
        the body runs means no task has been started yet.

        :raises ApprovalRequired: When this call delegates work and the
            gate is enabled; the delegation pauses on an approval card
            instead of starting.
        """
        if not self.enabled or tool_def.name != DELEGATE_TOOL_NAME:
            return args

        from pydantic_ai.exceptions import ApprovalRequired

        call_id = str(getattr(call, "tool_call_id", "") or "")
        if call_id and call_id in _pending_approvals:
            # This call is the one the user has now answered: it runs.
            _pending_approvals.remove(call_id)
            logger.info("delegation gate: approved delegation %s runs", call_id)
            return args

        agent_name, task_text = self._call_intent(args)
        if call_id:
            _pending_approvals.append(call_id)
            if len(_pending_approvals) > _MAX_PENDING_APPROVALS:
                del _pending_approvals[:-_MAX_PENDING_APPROVALS]
        logger.info("delegation gate: pausing delegation to %r", agent_name)
        raise ApprovalRequired(
            metadata={
                "origin": ORIGIN,
                "reason": (
                    f"The model wants to delegate this task to "
                    f"{agent_name or 'a sub-agent'}.\n\n"
                    f"{task_text}\n\n"
                    "Approve to let it start, or reject and tell me how to "
                    "proceed instead."
                )}
        )

    @staticmethod
    def _call_intent(args: Any) -> tuple[str, str]:
        """The agent a delegation names and its task text, for the card.

        Both are best-effort: a malformed call must still produce a card
        the user can read, so anything unreadable degrades to a label
        rather than to an error.

        :param args: The delegate tool's parsed arguments.
        :return: ``(agent name, truncated task text)``.
        """
        if not isinstance(args, dict):
            return "", "(no task text)"
        agent = str(args.get("agent_name") or "")
        task = str(args.get("task") or "")
        if len(task) > _MAX_TASK_CHARS:
            task = task[:_MAX_TASK_CHARS] + "…"
        return agent, task or "(no task text)"


__all__ = ["DelegationApprovalGate"]
