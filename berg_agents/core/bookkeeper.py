"""Core bookkeeping for berg_agents.

Manages a host-side worklog, task tracking, and memory pointers so that
`berg_agents` itself — not `.opencode` or any other plugin — owns the
record of what has happened. Plugins can read this state but the host
is the source of truth.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class Bookkeeper:
    """Maintain worklog, tasklist and memory pointers for the host."""

    def __init__(self, root: Path) -> None:
        """Initialize the bookkeeper.

        :param root: The root directory for the bookkeeper.
        :type root: Path
        """
        self.root = Path(root)
        self.worklog = self.root / "worklog.md"
        self.tasklist = self.root / "todo.md"

    def log_action(self, action: str, details: str) -> None:
        """Log an action to the worklog.

        :param action: The action to log.
        :type action: str
        :param details: The details of the action.
        :type details: str
        """
        timestamp = datetime.now().isoformat()
        with Path(self.worklog).open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {action}: {details}\n")

    def update_task(self, task_id: str, status: str) -> None:
        """Update the status of a task.

        :param task_id: The ID of the task to update.
        :type task_id: str
        :param status: The new status of the task.
        :type status: str
        """
        self.log_action("task_update", f"{task_id} -> {status}")
