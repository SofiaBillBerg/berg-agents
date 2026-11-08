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

"""The run context every agent in a delegation tree shares.

A delegated sub-agent runs with the *parent's* deps — that is the
library's contract, and it is what lets a sub-agent work in the same
workspace as the run that asked for it. So the type both sides use cannot
live in the implementer's own module: the chat agent, which has no notion
of "a task being implemented", needs the same class.

Two fields are load-bearing beyond the implementer:

* ``workspace_root`` — every file tool in the tree binds to it, so a
  delegate's relative paths land where the parent's would.
* ``changes`` — the implementer's mutating tools append here, and it is
  the ground truth for "did the work happen": the model's own summary is
  narration and may claim success for a write that never occurred.
  Callers report from here, never from the model's prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileChange:
    """One file a run actually modified on disk.

    Attributes:
        action: Which mutating tool did it (write/edit/patch).
        path: Workspace-relative path as the tool resolved it.
    """

    action: str
    path: str


@dataclass
class AgentDeps:
    """Dependencies injected into every agent run in the tree.

    Attributes:
        workspace_root: Workspace directory file tools are bound to.
        complexity: Task complexity level driving model selection.
        task_type: Task type being executed (e.g. ``"edit_file"``).
        changes: Every file this run actually wrote, appended by the
            mutating tools. This is the ground truth for "did the work
            happen" - the model's own summary is narration and may claim
            success for a write that never occurred. Callers report from
            here, never from the model's prose.
    """

    workspace_root: str = "."
    complexity: str = "standard"
    task_type: str = "generic"
    changes: list[Any] = field(default_factory=list)
