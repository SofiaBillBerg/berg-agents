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

"""Delegation as the chat agent's task-controlled sub-agent roster.

The staged ``implement_task`` delegate runs the implementer inside a tool
body that awaits it. That shape is what made the nested stream and the
plan gate possible, and it is also what makes the implementer
unsteerable: its writes are ungated, it cannot ask, and a Stop ends the
run while the command it is running keeps going.

The harness's ``SubAgents`` capability with ``TaskControl`` is the
library's answer to exactly that - a task can be messaged, answered,
cancelled with force, and resumed - so the roster is built here and
handed to the chat agent alongside the staged delegates. Phase 1 of the
migration is deliberately additive: both paths exist until the new one is
verified live, then the hand-rolled delegate is retired.

``sub_agents`` events arrive on the parent's own node stream, with no
relay at all.

What phase 1 does NOT yet carry is the nested stream, because the
harness's own events were arriving and being dropped silently by the
encoder: a delegated run showed the ``delegate_task`` card and nothing
inside it. Two facts settled that (probes
``/tmp/opencode/parent-stream-probe.py`` and
``/tmp/opencode/forward-events-probe.py``):

1. **Without forwarding, the child is invisible.** The parent's
   ``CallToolsNode`` yields ``FunctionToolCallEvent``, ``TaskAssigned``,
   ``TaskStarted``, ``DelegationStart``, ``DelegationEnd``,
   ``TaskCompleted`` and the tool result — and none of the child's own
   parts. The hand-rolled relay worked around this by driving the
   child's stream itself, but under ``SubAgents`` the handler is fixed
   at build time while the relay attaches per run, and the context
   handed to it is the *child's*, whose ``tool_call_id`` is ``None``:
   there was nothing to label the bracket with.
2. **With ``TaskControl(forward_events=True)`` the child's whole stream
   arrives on the parent's** as ``TaskProgressEvent(task_id, agent_name,
   event=<the child's native event>)``, bracketed by
   ``DelegationStartEvent`` and ``DelegationEndEvent``. The forwarded
   events are the very ``PartStartEvent`` / ``PartEndEvent`` /
   ``FunctionToolCallEvent`` / ``FunctionToolResultEvent`` /
   ``FinalResultEvent`` the relay's ``drive`` re-encodes, so the bracket
   and its content come from one mechanism.

So the roster is built with forwarding on, and the encoder learns to
read those events — which retires the hand-rolled relay instead of
side-channelling it. Sofia chose that direction on 2026-11-08.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The roster name the chat model uses in ``delegate_task``.
DELEGATE_NAME = "implementation"


def build_delegation_capabilities(
    plan_tools: dict[str, Any] | None = None, model_id: str | None = None
) -> list[Any]:
    """Build the delegation capabilities for the chat agent.

    The implementer is the same agent the staged delegate runs - one
    implementation, not two - wired as a roster entry with the plan
    store's tools so a delegated run reads and checks off the same plan
    the user sees.

    No workspace root is taken here: the implementer's file tools read
    ``ctx.deps.workspace_root``, so the root a delegated run works in is
    the one the chat run's deps carry, not one bound at build time.

    :param plan_tools: Session-bound plan-store tools, forwarded to the
        implementer exactly as ``_make_implement_task`` forwards them.
    :param model_id: Model the delegated implementer runs on. None keeps
        the tier default from configuration, which is what the implementer
        resolved to before the choice existed; an explicit id overrides it.
    :return: The capability list, or an empty list when delegation is
        unavailable (the staged delegates carry the turn alone).
    """
    try:
        from berg_agents.agents.implementation import (
            _resolve_child_approvals,
            _writes_gated,
            build_implementation_agent,
        )
        from pydantic_ai.capabilities import HandleDeferredToolCalls
        from pydantic_ai.usage import UsageLimits
        from pydantic_ai_harness import SubAgent, SubAgents
        from pydantic_ai_harness.subagents import TaskControl
    except ImportError as exc:  # pragma: no cover - older harness
        logger.warning(
            "delegation unavailable (%s); the staged delegates carry the turn",
            exc,
        )
        return []

    # Per-delegate budget. The library default of 50 requests would kill
    # the implementer mid-plan - the exact failure already recorded once
    # for the inline run (decision-log, UsageLimits(request_limit=None)).
    # forward_usage stays True so the chat run's budget still bounds the
    # whole tree.
    # The one rule a delegated implementer needs beyond the staged one:
    # it may ASK. The library's `TaskLink` tells the child its delegating
    # agent may steer it, and `SubAgents` tells the parent it can answer -
    # but nothing tells the child that stopping to ask is a legitimate
    # move. The default prompt actively works against it: the task IS the
    # plan, and "do NOT re-plan" plus "execute the steps" reads as "never
    # stop". Left unsaid, the model simply guesses - observed live: a child
    # told to ask a question replied "Got it! I will ask the user which
    # single file they want me to inspect" and then kept going, which is
    # the failure this text has to prevent: stating an intention is not
    # calling a tool.
    delegation_instructions = (
        "When a step needs a decision the task text does not answer - "
        "which file, which of two plausible readings, whether to overwrite "
        "something that exists - call ask_parent(question=...) and WAIT "
        "for the answer. Do not guess and do not proceed on an "
        "assumption.\n\n"
        "Asking means calling the ask_parent TOOL. Writing the question "
        "into your reply is not asking: your text goes back as your final "
        "answer, the task ends, and nobody ever answers it. If you find "
        "yourself typing a question mark at the user, stop and call "
        "ask_parent instead.\n\n"
        "Ask only when you cannot reasonably continue; a step the task "
        "answers outright is yours to do."
    )
    implementer = build_implementation_agent(
        plugin_tools=list((plan_tools or {}).values()),
        # None keeps the tier default, so a session that never chose still
        # behaves exactly as it did; a chosen model takes priority over it.
        model_id=model_id or None,
        extra_instructions=delegation_instructions,
    )
    return [
        SubAgents(
            agents=[
                SubAgent(
                    implementer,
                    name=DELEGATE_NAME,
                    description=(
                        "Executes a stored step plan in this workspace: "
                        "reads and writes the files the plan names and "
                        "checks each step off the todo list."
                    ),
                    usage_limits=UsageLimits(request_limit=None),
                    can_ask_questions=True,
                )
            ],
            task_control=TaskControl(forward_events=True),
            # The resolver for the implementer's gated writes. Registered
            # here rather than on the implementer itself because a
            # delegated child does not run with its agent's own capability
            # list - shared_capabilities is the harness's documented way to
            # give every delegated child one. Without it a gated write ends
            # the child's run on DeferredToolRequests: a soft outcome
            # nothing resumes, which is how this gap was first described.
            shared_capabilities=[
                HandleDeferredToolCalls(handler=_resolve_child_approvals)
            ]
            if _writes_gated()
            else [],
        )
    ]
