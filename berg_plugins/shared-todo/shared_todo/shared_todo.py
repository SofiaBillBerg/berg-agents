#  Berg Agents Shared ToDo Plugin
#
#  Copyright (c) 2026.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as
#  published by the Free Software Foundation, either version 3 of the
#  License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Shared ToDo Plugin for Berg Agents

Provides collaborative todo list management between user and agent.
Todos are stored as Markdown files for easy editing by both parties.
"""

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# Simple base classes to avoid circular imports
class BergPlugin:
    """Base interface for all berg_agents plugins."""

    def __init__(self) -> None:
        """Initialize the plugin."""
        self.context: Any = None

    async def on_load(self, context) -> None:
        """Called when plugin is loaded."""

    async def on_enable(self, context) -> None:
        """Called when plugin is enabled."""

    async def on_disable(self, context) -> None:
        """Called when plugin is disabled."""

    async def on_unload(self, context) -> None:
        """Called when plugin is unloaded."""

    def get_capabilities(self) -> list[Any]:
        """Return plugin capabilities (tools, agents, etc.)."""
        return []

    def get_settings_schema(self) -> dict[str, Any] | None:
        """Return JSON schema for plugin settings."""
        return None


class ToolCapability:
    """Tool capability provided by a plugin."""

    def __init__(
        self,
        type: str = "tool",
        id: str = "",
        name: str = "",
        description: str = "",
        tool=None,
    ) -> None:
        self.type = type
        self.id = id
        self.name = name
        self.description = description
        self.tool = tool


class TodoSettings(BaseModel):
    """Settings for the shared todo plugin."""

    todo_path: str = "./sharedtodos/"


class TodoItem(BaseModel):
    """A todo item."""

    id: str
    title: str
    description: str = ""
    status: str = "todo"  # todo, in_progress, done
    created_at: str
    updated_at: str
    completed_at: str | None = None


class SharedToDoPlugin(BergPlugin):
    """Shared ToDo plugin for collaborative planning.

    Enables users and agents to create, manage, and share todo lists
    as Markdown files.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self.settings: TodoSettings | None = None
        self.todo_dir: Path | None = None
        self.context: Any = None

    async def on_load(self, context: Any) -> None:
        """Load plugin and initialize todo directory.

        Args:
            context: Plugin context
        """
        logger.info(f"Loading {context.plugin_id}")

        self.context = context

        # Parse settings - use defaults if no settings provided
        settings_dict = getattr(context, "settings", {})
        self.settings = TodoSettings(**settings_dict)

        # Initialize todo directory
        self.todo_dir = Path(self.settings.todo_path)
        self.todo_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Todo directory: {self.todo_dir}")
        logger.info("Shared ToDo plugin loaded successfully")

    async def on_enable(self, context: Any) -> None:
        """Enable plugin and register tools.

        Args:
            context: Plugin context
        """
        logger.info(f"Enabling {context.plugin_id}")

        # Subscribe to events if needed
        # await context.event_bus.subscribe("task.*", self._on_task_event)

        logger.info("Shared ToDo plugin enabled")

    async def on_disable(self, context: Any) -> None:
        """Disable plugin.

        Args:
            context: Plugin context
        """
        logger.info(f"Disabling {context.plugin_id}")

        # Unsubscribe from events
        # await context.event_bus.unsubscribe("task.*", self._on_task_event)

    async def on_unload(self, context: Any) -> None:
        """Unload plugin.

        Args:
            context: Plugin context
        """
        logger.info(f"Unloading {context.plugin_id}")

    def get_capabilities(self) -> list[ToolCapability]:
        """Return plugin capabilities.

        Returns:
            List of tool capabilities
        """
        # Return tool capability with our todo management functions
        from feat_dev.plugin_dev.berg_plugins.shared_todo.tools import (
            complete_todo,
            create_todo,
            list_todos,
            update_todo,
        )

        return [
            ToolCapability(
                type="tool",
                id="shared_todo",
                name="Shared ToDo",
                description="Manage shared todo lists",
                tool=create_todo,
            ),
            ToolCapability(
                type="tool",
                id="list_todos",
                name="List Todos",
                description="List all todos",
                tool=list_todos,
            ),
            ToolCapability(
                type="tool",
                id="update_todo",
                name="Update Todo",
                description="Update a todo item",
                tool=update_todo,
            ),
            ToolCapability(
                type="tool",
                id="complete_todo",
                name="Complete Todo",
                description="Mark a todo as completed",
                tool=complete_todo,
            )]

    def get_settings_schema(self) -> dict[str, Any] | None:
        """Return settings schema.

        Returns:
            JSON schema for plugin settings
        """
        return {
            "type": "object",
            "properties": {
                "todo_path": {
                    "type": "string",
                    "description": "Path to directory for todo lists",
                    "default": "./sharedtodos/"}
            }}

    # Helper methods for todo management

    def _get_todo_path(self, todo_id: str) -> Path:
        """Get path to a todo file.

        Args:
            todo_id: Todo identifier

        Returns:
            Path to todo Markdown file
        """
        assert self.todo_dir is not None
        return self.todo_dir / f"{todo_id}.md"

    def _list_todo_files(self) -> list[Path]:
        """List all todo files.

        Returns:
            List of todo file paths
        """
        assert self.todo_dir is not None
        return list(self.todo_dir.glob("*.md"))

    def _create_todo_file(self, todo: TodoItem) -> None:
        """Create a todo Markdown file.

        Args:
            todo: Todo item to save
        """
        path = self._get_todo_path(todo.id)

        content = f"""# {todo.title}

**Status:** {todo.status}  
**Created:** {todo.created_at}  
**Updated:** {todo.updated_at}  
{f"**Completed:** {todo.completed_at}  " if todo.completed_at else ""}

## Description

{todo.description}

## Notes

<!-- Add notes here -->
"""

        path.write_text(content)
        logger.info(f"Created todo file: {path}")

    def _parse_todo_file(self, path: Path) -> TodoItem:
        """Parse a todo Markdown file.

        Args:
            path: Path to todo file

        Returns:
            Parsed todo item
        """
        content = path.read_text()
        lines = content.split("\n")

        # Parse title (first line after #)
        title = lines[0].replace("# ", "").strip()

        # Parse metadata
        status = "todo"
        created_at = ""
        updated_at = ""
        completed_at = None

        for line in lines[1:10]:  # Check first 10 lines for metadata
            if line.startswith("**Status:**"):
                status = line.split("**Status:**")[1].strip()
            elif line.startswith("**Created:**"):
                created_at = line.split("**Created:**")[1].strip()
            elif line.startswith("**Updated:**"):
                updated_at = line.split("**Updated:**")[1].strip()
            elif line.startswith("**Completed:**"):
                completed_at = line.split("**Completed:**")[1].strip()

        # Extract description
        description = ""
        in_desc = False
        for line in lines:
            if line.startswith("## Description"):
                in_desc = True
                continue
            elif line.startswith("## Notes"):
                break
            elif in_desc:
                description += line + "\n"

        return TodoItem(
            id=path.stem,
            title=title,
            description=description.strip(),
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
        )
