"""Workspace toolset for berg_agents chat agents.

Wraps the framework-free :class:`~berg_agents.core.tool_spec.ToolSpec`
instances from :func:`~berg_agents.agents.factory.create_tools` in a
single named pydantic-ai toolset, following the documented custom-toolset
pattern (subclass :class:`~pydantic_ai.toolsets.WrapperToolset`,
override the extension points you need, delegate the rest).

Why a toolset instead of loose ``tool_plain`` registrations:

- One stable ``id`` (``"workspace"``) identifying every instruction
  and tool the workspace contributes - addressable as
  ``toolset:workspace`` and safe for durable execution.
- One ``get_instructions`` block teaching explore-first usage, instead
  of repeating usage guidance per tool and in the system prompt.
- Dynamic membership: ``read_only`` / ``allow_shell`` constructor
  flags select the registered subset per deployment, and ``call_tool``
  is the single audit/logging switch for every invocation.
- The harness loop and ``POST /api/tool/execute`` keep using the raw
  :class:`ToolSpec` list - this toolset is the pydantic-ai view of
  the same single source, not a second one.
"""

#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import annotations

import asyncio
import json
import logging

from pathlib import Path
from typing import Any

from pydantic_ai.toolsets.wrapper import WrapperToolset


logger = logging.getLogger(__name__)

#: Stable toolset id. Instruction parts from
#: :meth:`WorkspaceToolset.get_instructions` are addressable as
#: ``toolset:workspace``; keep it constant - durable execution and
#: log readers key off this string, never the wording.
WORKSPACE_TOOLSET_ID = "workspace"

#: Usage guide injected into the agent's instructions once per run.
#: Complements (not replaces) the system prompt's authoritative tool
#: list: this text teaches *how* to work the filesystem, the prompt
#: names *what* exists.
_WORKSPACE_INSTRUCTIONS = """\
Workspace tools (toolset `workspace`) - how to work the filesystem:

- EXPLORE FIRST: call list_files before reading anything. Never guess
  at paths; use the exact paths list_files returns.
- Directories are not files: read_file on a directory tells you so -
  follow its guidance instead of retrying.
- SEARCH before assuming: use search_code to find definitions,
  references, or error strings instead of reading trees by hand.
- RUN things with bash (tests, builds, inspection). It has a timeout
  and truncated output; long jobs should be split or backgrounded by
  the caller. There is no other shell tool.
- WRITE with intent: write_file creates, edit_file replaces. Both
  need human approval in chat - the user sees an approve/reject
  dialog, so say what you are about to do before calling.
- COMPLEX work (multi-step plans, refactors, research) starts with
  plan_task, then implement_task runs the approved plan. Each stage
  streams its own result — progress stays visible.
- If a tool answers "not found" or "is a directory", follow the
  message. Do not retry the same call and do not invent tool names —
  the toolset above is the complete inventory.
"""


class WorkspaceToolset(WrapperToolset[None]):
    """File/shell workspace tools as one named, dynamic toolset.

    Builds an inner :class:`FunctionToolset` from
    :func:`~berg_agents.agents.factory.create_tools` (the same specs
    the harness loop and ``/api/tool/execute`` run) plus staged
    ``plan_task`` / ``implement_task`` subagent delegates, then adds
    identity, instructions, dynamic membership, and an audited call
    path on top.

    :param root_dir: Workspace root all file tools are bound to.
    :param read_only: When True, only low-risk tools (list, read,
        search) are registered - the model cannot change files even
        if it tries. Mutating tools are withheld, not merely
        instructed away.
    :param allow_shell: When False, the ``bash`` tool is withheld
        (safe default for untrusted deployments).
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        read_only: bool = False,
        allow_shell: bool = True,
    ) -> None:
        """Initialize the workspace toolset.

        :param root_dir: Workspace root all file tools are bound to.
        :param read_only: When True, only low-risk tools (list, read,
            search) are registered - the model cannot change files even
            if it tries. Mutating tools are withheld, not merely
            instructed away.
        :param allow_shell: When False, the ``bash`` tool is withheld
            (safe default for untrusted deployments).
        """
        from pydantic_ai.toolsets import FunctionToolset

        from berg_agents.agents.factory import create_tools

        inner: FunctionToolset[None] = FunctionToolset()
        for spec in create_tools(root_dir):
            if spec.execute is None:
                logger.warning(
                    "ToolSpec '%s' has no execute callable; skipping",
                    spec.name,
                )
                continue
            risk = spec.risk_class or "medium"
            if read_only and risk != "low":
                continue
            if not allow_shell and spec.name == "bash":
                continue
            inner.add_function(
                spec.execute,
                name=spec.name,
                description=spec.description or spec.name,
                requires_approval=risk != "low",
            )
        if not read_only:
            # Staged delegation: plan first (read-only, no approval),
            # then implement against the approved plan (approval-gated).
            # Each stage streams its own result, so progress stays
            # visible instead of vanishing inside one opaque call.
            inner.add_function(
                _make_plan_task(),
                name="plan_task",
                description=(
                    "Decompose a task into an ordered step plan via the "
                    "planner subagent. Call this before implement_task "
                    "on any multi-step work."
                ),
                requires_approval=False,
                timeout=240.0,
            )
            inner.add_function(
                _make_implement_task(str(root_dir)),
                name="implement_task",
                description=(
                    "Execute an approved step plan via the implementation "
                    "subagent (workspace-rooted file tools). Only call "
                    "with a plan the user has seen."
                ),
                requires_approval=True,
                timeout=600.0,
            )
        super().__init__(wrapped=inner)
        self._root_dir = str(root_dir)

    @property
    def id(self) -> str | None:
        """Stable toolset id (``"workspace"``).

        :return: Toolset id.
        """
        return WORKSPACE_TOOLSET_ID

    async def get_instructions(self, ctx: Any) -> str:
        """Workspace usage guide, injected once per run.

        :param ctx: Context from the agent.
        :return: Usage instructions for the workspace toolset.
        """
        _ = ctx
        return _WORKSPACE_INSTRUCTIONS

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: Any,
        tool: Any,
    ) -> Any:
        """Audit-log every invocation, then delegate to the toolset.

        The single switch for all workspace tool execution: approval
        gating, retries, and result handling stay in the framework
        (via each tool's registration metadata); this layer owns
        observability.
        """
        logger.info("workspace tool call: %s(%s)", name, tool_args)
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except Exception as exc:
            logger.warning("workspace tool %s failed: %s", name, exc)
            raise
        logger.debug(
            "workspace tool %s returned %d chars", name, len(str(result))
        )
        return result


def _make_plan_task() -> Any:
    """Build the ``plan_task`` delegate (planner subagent, read-only)."""

    async def _plan_task(description: str) -> str:
        """Decompose a task into an ordered step plan.

        Calls the planner subagent in an isolated run and returns
        its plan as text. Read-only: plans nothing, changes nothing.
        Always plan before implementing multi-step work.

        :param description: What needs doing, in plain language.
        :return: Numbered step plan as text.
        """
        from berg_agents.agents.planner import PlannerDeps, build_planner_agent

        agent = build_planner_agent()
        result = await agent.run(description, deps=PlannerDeps())
        return str(result.output)

    return _plan_task


def _make_implement_task(root_dir: str) -> Any:
    """Build the ``implement_task`` delegate (implementation subagent)."""

    async def _implement_task(plan: str, task_type: str = "generic") -> str:
        """Execute an approved step plan via the implementation subagent.

        Runs in an isolated run with workspace-rooted file tools and
        returns what was done. Only call with a plan the user has
        seen — execution needs human approval first.

        :param plan: The step plan to execute (from ``plan_task``).
        :param task_type: Task type label for model routing.
        :return: Execution summary as text.
        """
        from berg_agents.agents.implementation import (
            ImplementationDeps,
            build_implementation_agent,
        )

        agent = build_implementation_agent()
        result = await agent.run(
            plan,
            deps=ImplementationDeps(
                workspace_root=root_dir, task_type=task_type
            ),
        )
        return str(result.output)

    return _implement_task
