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
Shared ToDo Plugin for Berg Agents.

Provides collaborative todo list management between user and agent.
Todos are stored as Markdown files for easy editing by both parties.


In the function on_load(), the plugin performs several validation checks to ensure that it is configured correctly and can operate as expected. The following table summarizes the key validation steps, where they occur, and what happens if they fail:

-------------------------------------------------------
# Check -> Where it happens -> What it raises if it fails
----------------------------------------------------------
    - Plugin settings schema -> TodoSettings(**context.settings) -> RuntimeError with ValidationError details
    - User env and config file -> validate_user_config() -> RuntimeError with a clear “User config error” message
    - Distribution mode	-> is_plugin_installable() vs is_integrated_into_berg_agents() -> Logs a friendly note – no exception
    - Extra config‑field validation	-> validate_shared_todo_config(your_extra_dict) (optional) -> RuntimeError with Pydantic validation errors
"""

import logging
from pathlib import Path
from typing import Any

from shared_todo.shared_todo_distribution import (
    is_integrated_into_berg_agents,
    is_plugin_installable,
)
from shared_todo.shared_todo_user_cfg import validate_user_config

# NOTE: Use the real plugin base classes so PluginManager's
# isinstance(plugin, BergPlugin) check passes. The previous local
# dummy BergPlugin/ToolCapability stubs broke discovery.
from plugin_system.lifecycle.bergplugin import BergPlugin
from plugin_system.plugin_context import PluginContext
from plugin_system.plugin_contract import ToolCapability
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


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
        # NOTE: Base class tracks event bus + plugin id internally.
        super().__init__()
        self.settings: TodoSettings | None = None
        self.todo_dir: Path | None = None
        self.context: PluginContext | None = None

    async def on_load(self, context: PluginContext) -> None:
        """Load plugin and initialize todo directory.

        Args:
            context: Plugin context
        """
        logger.info(f"Loading {context.plugin_id}")

        self.context = context
        self._set_event_bus(context.event_bus, context.plugin_id)

        # --------------------------------------------------------------
        # Validate the plugin’s own settings (TodoSettings)
        # --------------------------------------------------------------
        try:
            # Parse settings - use defaults if no settings provided.
            # PluginContext.settings is a plain dict from the config manager.
            # context.settings is a plain dict; coerce it to our config model
            self.settings = TodoSettings(**context.settings or {})
            logger.info(f"Plugin settings validated: {self.settings}")
        except ValidationError as ve:
            raise RuntimeError(f"Invalid plugin settings: {ve}") from ve

        # --------------------------------------------------------------
        # Validate the *configuration* that may be supplied by the user
        # --------------------------------------------------------------
        try:
            user_cfg = (
                validate_user_config()
            )  # reads env + ~/.shared_todo/config.yaml
            logger.info(f"User configuration validated: {user_cfg}")
        except ValueError as cfg_err:
            raise RuntimeError(
                f"User config error – aborting plugin load: {cfg_err}"
            ) from cfg_err

        # --------------------------------------------------------------
        # Detect distribution mode (stand‑alone plugin vs. integrated)
        # --------------------------------------------------------------
        if is_plugin_installable():
            logger.info("⚡ Running as a **stand‑alone installable plugin**.")
        elif is_integrated_into_berg_agents():
            logger.info("⚡ Running **integrated** inside berg‑agents.")
        else:
            logger.warning(
                "⚠️  Could not determine distribution mode – proceeding anyway."
            )

        # --------------------------------------------------------------
        # 4️⃣ Validate that all required configuration fields are present
        # --------------------------------------------------------------
        # Example: you might have extra required keys in your own config.
        # If you need extra validation, build a small dict and call:
        #   validated = validate_shared_todo_config(extra_cfg)
        # Any ValidationError will be raised automatically.

        logger.info("✅ Shared ToDo plugin loaded successfully")

        # Initialize todo directory
        self.todo_dir = Path(self.settings.todo_path)
        self.todo_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Todo directory: {self.todo_dir}")
        logger.info("Shared ToDo plugin loaded successfully")

    async def on_enable(self, context: PluginContext) -> None:
        """Enable plugin and register tools.

        Args:
            context: Plugin context
        """
        logger.info(f"Enabling {context.plugin_id}")

        # Subscribe to events if needed
        # await context.event_bus.subscribe("task.*", self._on_task_event)

        logger.info("Shared ToDo plugin enabled")

    async def on_disable(self, context: PluginContext) -> None:
        """Disable plugin.

        Args:
            context: Plugin context
        """
        logger.info(f"Disabling {context.plugin_id}")

        # Unsubscribe from events
        # await context.event_bus.unsubscribe("task.*", self._on_task_event)

    async def on_unload(self, context: PluginContext) -> None:
        """Unload plugin.

        Args:
            context: Plugin context
        """
        logger.info(f"Unloading {context.plugin_id}")

    def get_capabilities(self) -> list[ToolCapability]:
        """Return plugin capabilities.

        Each todo function is wrapped in a pydantic-ai Tool so the
        agent runtime can call it with a generated JSON schema.

        Returns:
            List of tool capabilities
        """
        # NOTE: Absolute package import works when the plugin dir is
        # on sys.path (see PluginManager._import_plugin).
        from shared_todo.tools import (
            add_subtask,
            complete_todo,
            create_todo,
            delete_subtask,
            delete_todo,
            list_todo_items,
            list_todos,
            rename_subtask,
            set_subtask_done,
            update_todo,
        )

        from pydantic_ai.tools import Tool

        return [
            ToolCapability(tool=Tool(create_todo), risk_level="low"),
            ToolCapability(tool=Tool(list_todos), risk_level="low"),
            ToolCapability(tool=Tool(list_todo_items), risk_level="low"),
            ToolCapability(tool=Tool(update_todo), risk_level="low"),
            ToolCapability(tool=Tool(complete_todo), risk_level="low"),
            ToolCapability(tool=Tool(delete_todo), risk_level="low"),
            ToolCapability(tool=Tool(add_subtask), risk_level="low"),
            ToolCapability(tool=Tool(set_subtask_done), risk_level="low"),
            ToolCapability(tool=Tool(rename_subtask), risk_level="low"),
            ToolCapability(tool=Tool(delete_subtask), risk_level="low")]

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
        content = path.read_text(encoding="utf-8")
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
