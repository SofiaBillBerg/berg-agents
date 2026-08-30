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
        self.root = Path(root)
        self.worklog = self.root / "worklog.md"
        self.tasklist = self.root / "todo.md"

    def log_action(self, action: str, details: str) -> None:
        timestamp = datetime.now().isoformat()
        with Path(self.worklog).open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {action}: {details}\n")

    def update_task(self, task_id: str, status: str) -> None:
        self.log_action("task_update", f"{task_id} -> {status}")
