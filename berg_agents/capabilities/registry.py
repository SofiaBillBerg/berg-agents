# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Tool catalog - single source of truth for tool routing.

Replaces duplicate hardlists previously scattered across
``agents/implementation``, ``agents/planner``, and
``core/harness/_routing``.
"""

from __future__ import annotations


class _ToolCatalogImpl:
    """Internal tool-routing constants and helpers.

    This is the single source for tool routing names and requirements,
    used by :mod:`berg_agents.core.harness._routing` to decide which
    tools a given task type needs.
    """

    EXECUTION_KEYWORDS: tuple[str, ...] = (
        "write",
        "edit",
        "create",
        "modify",
        "delete",
        "run",
        "execute",
        "implement",
        "fix",
    )

    TOOL_REQUIREMENTS: dict[str, list[str]] = {
        "edit_file": ["read_file", "edit_file"],
        "new_file": ["new_file"],
        "read_file": ["read_file"],
        "delete_file": ["delete_file"],
        "generate_test": ["read_file", "new_file"],
        "format_code": ["read_file", "edit_file"],
        "execute_command": ["execute_command"]}

    @classmethod
    def tools_for(cls, task_type: str, description: str = "") -> list[str]:
        """Tools for a given task type.

        :param task_type: Task type string (e.g. ``"edit_file"``).
        :param description: Optional task description to help infer
            tool requirements when the task type is unknown.
        :return: List of tool names (e.g. ``["read_file", "edit_file"]``).

        Example::

            >>> result = tools_for(task_type="example_task_type")
        """
        if task_type in cls.TOOL_REQUIREMENTS:
            return list(cls.TOOL_REQUIREMENTS[task_type])
        lowered = description.lower()
        if any(kw in lowered for kw in cls.EXECUTION_KEYWORDS):
            return ["read_file", "write_file", "edit_file"]
        return ["general"]


# Public alias - kept for backward compatibility with callers that do
# ``from berg_agents.capabilities.registry import ToolCatalog``.
ToolCatalog = _ToolCatalogImpl

# Re-export for convenience.
__all__ = ["ToolCatalog"]
