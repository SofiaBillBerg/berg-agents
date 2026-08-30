import json
import logging

from pathlib import Path
from typing import Any, List

from berg_agents.core.interface import AbstractAgent, AgentResult, TaskContext
from berg_agents.plugins.collaborative_todo.schema import Todo, TodoState


# SKYLOS DEADCODE START (lines 3-3)
# import os
# SKYLOS DEADCODE END
pass




logger = logging.getLogger(__name__)

TODOS_FILE = Path(".cache/collaborative_todo_todos.json")


class CollaborativeTodoAgent(AbstractAgent):
    """Plugin agent for managing collaborative todos."""

    name: str = "collaborative_todo"
    description: str = (
        "Manages a shared list of tasks (todos) that can be viewed and updated."
    )
    preferred_model_tier: str = "medium"
    capabilities: list[str] = [
        "manage_todo_list",
        "track_progress",
        "assign_tasks",
        "create_todo",
        "complete_todo",
        "update_todo",
    ]

    def _load_todos(self) -> list[Todo]:
        if not TODOS_FILE.exists():
            return []
        try:
            with open(TODOS_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return [Todo(**item) for item in data]
        except Exception as e:
            logger.error(f"Error loading todos: {e}")
            return []

    def _save_todos(self, todos: list[Todo]):
        TODOS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TODOS_FILE, "w", encoding="utf-8") as f:
            json.dump([item.dict() for item in todos], f, indent=2)

    def can_handle(self, task: dict[str, Any]) -> float:
        desc = task.get("description", "").lower()
        task_type = task.get("task_type", "").lower()

        keywords = [
            "todo",
            "task list",
            "roadmap",
            "action items",
            "complete task",
            "add task",
        ]

        if any(kw in desc for kw in keywords) or task_type == "todo_management":
            return 1.0

        return 0.5

    def execute(
        self, task: dict[str, Any], context: TaskContext, model: Any = None
    ) -> AgentResult:
        todos = self._load_todos()
        desc = task.get("description", "").lower()

        # Basic command parsing
        if "add" in desc and (":" in desc or len(desc.split()) > 5):
            # Try to extract content after a colon
            try:
                parts = desc.split(":", 1)
                content = parts[1].strip()
                new_todo = Todo(content=content, description="Added via CLI")
                todos.append(new_todo)
                self._save_todos(todos)
                return AgentResult(
                    status=True,
                    output={"message": "Todo added.", "todos": todos},
                    metadata={"count": len(todos)},
                )
            except Exception:
                pass

        elif "list" in desc or "show" in desc or "view" in desc:
            return AgentResult(success=True, output={"todos": todos})

        elif "complete" in desc:
            # Look for ID (UUID)
            # This is a bit simplified, better would be actual NLP, but let's try finding something looking like UUID
            # ... implementation for completion ...
            pass

        # Fallback/Default: Just return the list if unsure
        return AgentResult(
            success=True,
            output={
                "todos": todos,
                "message": "Please specify action (add, list, complete).",
            },
        )
