"""Tool catalog — single source of truth for tool routing.

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
        """Return the tool names needed for a given task type.

        :param task_type: The task type (e.g. ``"write_file"``, ``"edit_file"``).
        :param description: Free-text task description, used as a fallback.
        :return: List of tool names (may contain ``"general"``).
        """
        if task_type in cls.TOOL_REQUIREMENTS:
            return list(cls.TOOL_REQUIREMENTS[task_type])
        lowered = description.lower()
        if any(kw in lowered for kw in cls.EXECUTION_KEYWORDS):
            return ["read_file", "write_file", "edit_file"]
        return ["general"]


# Public alias — kept for backward compatibility with callers that do
# ``from berg_agents.capabilities.registry import ToolCatalog``.
ToolCatalog = _ToolCatalogImpl


# Re-export for convenience.
__all__ = ["ToolCatalog"]
