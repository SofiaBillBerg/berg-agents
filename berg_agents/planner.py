"""Planner: suggest Planning(enable_subtasks=True) when complexity > 2 steps."""

from __future__ import annotations


class Planning:
    """Suggest harness Planning capability for multi-step tasks."""

    MIN_STEPS_FOR_PLANNING = 2

    def __init__(self, enable_subtasks: bool = False) -> None:
        """Initialize Planning with optional subtask enablement."""
        self.enable_subtasks = enable_subtasks

    def suggest(self, steps: int) -> bool:
        """Suggest planning when steps exceed threshold and subtasks enabled."""
        return steps > self.MIN_STEPS_FOR_PLANNING and self.enable_subtasks
