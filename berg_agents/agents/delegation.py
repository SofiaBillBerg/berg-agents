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

What phase 1 does NOT yet carry is the nested stream. The hand-rolled
delegate drives the implementer's own events through
:class:`~berg_agents.ui.subagent_relay.SubagentRelay` because it holds
the relay in a holder the web layer fills per run, and the bracket it
emits must name the parent tool call the child belongs to. Under
``SubAgents`` the handler is fixed at build time and the child's run
context carries no reference to the ``delegate_task`` call
(``tool_call_id`` is ``None`` there), so there is nothing to label the
bracket with yet. The child's stream is drained either way, so a
delegated run is silent rather than broken; wiring it is its own step.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The roster name the chat model uses in ``delegate_task``.
DELEGATE_NAME = "implementation"


def build_delegation_capabilities(
    root_dir: str, plan_tools: dict[str, Any] | None = None
) -> list[Any]:
    """Build the delegation capabilities for the chat agent.

    The implementer is the same agent the staged delegate runs - one
    implementation, not two - wired as a roster entry with the plan
    store's tools so a delegated run reads and checks off the same plan
    the user sees.

    :param root_dir: Workspace root the implementer's file tools bind to.
        It is also what the shared deps carry, so a delegated run works
        in the same workspace as the chat.
    :param plan_tools: Session-bound plan-store tools, forwarded to the
        implementer exactly as ``_make_implement_task`` forwards them.
    :return: The capability list, or an empty list when delegation is
        unavailable (the staged delegates carry the turn alone).
    """
    try:
        from berg_agents.agents.implementation import build_implementation_agent
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
    implementer = build_implementation_agent(
        plugin_tools=list((plan_tools or {}).values())
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
            task_control=TaskControl(),
        )
    ]
