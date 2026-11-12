# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
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

"""Agent factory for berg_agents.

Framework-free factory that wires the core loop, backend, and file tools.
Uses ``core.tool_spec.make_tool_spec``, ``core.loop.BergLoop``,
``backends.BackendAdapter``, and ``tools._io`` helpers.

Exposes clean names: ``build_agent`` / ``build_loop`` / ``create_tools``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from berg_agents.config.settings import DEFAULT_SYSTEM_PROMPT
from berg_agents.core.checkpoint import Checkpointer
from berg_agents.core.loop import BergLoop
from berg_agents.tools.tool_spec import ToolRegistry, ToolSpec, make_tool_spec
from berg_agents.tools._io import _atomic_write, _normalize_target

__all__ = ["DEFAULT_SYSTEM_PROMPT", "build_agent", "build_loop", "create_tools"]

# Re-exported so `from berg_agents.agents.factory import create_tools` -- the
# import every existing caller uses -- keeps working. The definitions moved to
# berg_agents/tools/specs.py so agents/implementation.py can read the tool
# inventory without importing this module and closing an import cycle.
from berg_agents.tools.specs import (  # noqa: F401
    RiskClass,
    ToolSpec,
    _normalize_target,
    _resolve_root,
    create_tools,
    make_tool_spec,
            )


def build_loop(
    adapter: Any,
    tools: Sequence[ToolSpec] | None = None,
    *,
    root_dir: str | Path = ".",
    interrupt_on: Mapping[str, bool] | None = None,
    max_steps: int = 25,
    checkpointer: Checkpointer | None = None,
) -> BergLoop:
    """Build a BergLoop wired for this project.

    :param adapter: Object exposing ``chat(messages, *, tools, temperature)``.
    :param tools: Optional ToolSpecs. Defaults to ``create_tools(root_dir)``.
    :param root_dir: Working directory mounted at /workspace/.
    :param interrupt_on: Optional {tool_name: bool} HITL map.
    :param max_steps: Hard step limit.
    :param checkpointer: Optional checkpointer.
    :return: Configured BergLoop.
        """
    from berg_agents.core.hitl import default_interrupt_on

    registry = ToolRegistry()
    for spec in tools if tools is not None else create_tools(root_dir=root_dir):
        registry.register(spec)

    effective_interrupt: dict[str, bool] = (
        dict(interrupt_on)
        if interrupt_on is not None
        else default_interrupt_on(dict(registry._tools.items()))
        )

    return BergLoop(
        adapter=adapter,
        tool_registry=registry,
        interrupt_on=effective_interrupt,
        max_steps=max_steps,
        checkpointer=checkpointer,
            )


def build_agent(
    adapter: Any,
    tools: Sequence[ToolSpec] | None = None,
    *,
    root_dir: str | Path = ".",
    system_prompt: str | None = None,
    interrupt_on: Mapping[str, bool] | None = None,
    max_steps: int = 25,
    checkpointer: Checkpointer | None = None,
) -> BergLoop:
    """Build an agent loop with a system prompt.

    Thin wrapper over ``build_loop`` that stashes ``system_prompt`` on the
    returned loop for callers to prepend to messages before ``run``.

    :param adapter: LLM adapter (e.g. BackendAdapter).
    :param tools: Optional ToolSpecs.
    :param root_dir: Working directory.
    :param system_prompt: Base system prompt.
    :param interrupt_on: Optional HITL policy.
    :param max_steps: Hard step limit.
    :param checkpointer: Optional checkpointer.
    :return: Configured BergLoop with ``system_prompt`` attribute.
        """
    loop = build_loop(
        adapter=adapter,
        tools=tools,
        root_dir=root_dir,
        interrupt_on=interrupt_on,
        max_steps=max_steps,
        checkpointer=checkpointer,
            )
    loop.system_prompt = (
        system_prompt if system_prompt is not None else DEFAULT_SYSTEM_PROMPT
    )  # type: ignore[attr-defined]
    return loop
