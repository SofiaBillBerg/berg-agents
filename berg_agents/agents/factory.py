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
Uses ``tools.tool_spec.make_tool_spec``, ``core.loop.BergLoop``,
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
from berg_agents.tools.tool_spec import ToolRegistry

__all__ = ["DEFAULT_SYSTEM_PROMPT", "build_agent", "build_loop", "create_tools"]


from pathlib import Path

from berg_agents.tools.tool_spec import ToolSpec, make_tool_spec
from berg_agents.tools._io import _atomic_write, _normalize_target

# The workspace tool specs live in berg_agents/tools/workspace_toolset.py, next
# to the toolset that wraps them and the ToolSpec type they are built from.
# Re-exported here so every existing `from berg_agents.agents.factory import
# create_tools` keeps working -- one definition, two names.
from berg_agents.tools.workspace_toolset import (  # noqa: F401
    RiskClass,
    ToolSpec,
    _normalize_target,
    _resolve_root,
    create_tools,
    make_tool_spec,
)

