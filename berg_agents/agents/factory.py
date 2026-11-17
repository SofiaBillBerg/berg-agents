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

"""Import-order anchor for the agents package.

This module once built the framework-free ``BergLoop`` and re-exported the
workspace ToolSpecs. Both are gone: every agent is now a pydantic-ai agent
whose tools come from the harness capabilities (see
``tools/workspace_toolset.py``), and no caller ever built a loop through
here. What remains is what made this module load-bearing: it is the FIRST
import in ``berg_agents.agents.__init__`` so core.interface is pre-loaded
via ``core.__init__``, and it re-exports the default system prompt.

Exposes one clean name: ``DEFAULT_SYSTEM_PROMPT``.
"""

from __future__ import annotations

from berg_agents.config.settings import DEFAULT_SYSTEM_PROMPT

# Deliberate pre-load, and the reason this module is imported FIRST in
# berg_agents.agents.__init__: importing berg_agents.core executes its
# package __init__, which reaches core.harness.orchestrator — and that
# module imports from berg_agents.agents.guardian at module level.
# Reaching it from inside guardian's own import is a cycle (guardian is
# only partially initialized at that point); reaching it HERE first loads
# guardian fresh and the cycle never closes. Keep this import ahead of any
# use of the re-export below.
import berg_agents.core  # ruff: ignore[unused-import] - imported for its load-order effect

__all__ = ["DEFAULT_SYSTEM_PROMPT"]
