#  Berg Agents Shared ToDo Plugin - Tools
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
Tool functions for Shared ToDo plugin.

These functions are exposed to the AI agent for todo list management.
"""

from datetime import datetime
import logging
from pathlib import Path
from typing import Annotated

logger = logging.getLogger(__name__)


def create_todo(
    title: Annotated[str, "Title of the todo item"],
    description: Annotated[
        str, "Detailed description of what needs to be done"
    ] = "",
    todo_path: str = "./sharedtodos/",
) -> str:
    """Create a new todo item.

    Creates a new todo item and saves it as a Markdown file in the shared
    todo directory. Both user and agent can edit these files.

    Args:
        title: Title of the todo item
        description: Detailed description
        todo_path: Path to todo directory

    Returns:
        Success message with todo ID
    """
    # Generate ID from title
    todo_id = title.lower().replace(" ", "_").replace("/", "_")[:50]
    timestamp = datetime.now().isoformat()

    # Ensure directory exists
    todo_dir = Path(todo_path)
    todo_dir.mkdir(parents=True, exist_ok=True)

    # Create todo file
    todo_file = todo_dir / f"{todo_id}.md"

    content = f"""# {title}

**Status:** todo  
**Created:** {timestamp}  
**Updated:** {timestamp}  

## Description

{description}

## Notes

<!-- Add notes here -->
"""

    todo_file.write_text(content)
    logger.info(f"Created todo: {todo_id}")

    return f"Created todo '{title}' with ID: {todo_id}\nFile: {todo_file}"


def list_todos(
    status: Annotated[
        str | None, "Filter by status: todo, in_progress, done, or None for all"
    ] = None,
    todo_path: str = "./sharedtodos/",
) -> str:
    """List all todo items.

    Lists all todos in the shared directory. Can be filtered by status.

    Args:
        status: Optional status filter (todo, in_progress, done)
        todo_path: Path to todo directory

    Returns:
        Formatted list of todos
    """
    todo_dir = Path(todo_path)

    if not todo_dir.exists():
        return "No todos found. Todo directory does not exist yet."

    todo_files = list(todo_dir.glob("*.md"))

    if not todo_files:
        return "No todos found."

    # Parse and filter todos
    todos = []
    for file_path in todo_files:
        try:
            content = file_path.read_text()
            lines = content.split("\n")

            # Parse title and status
            title = lines[0].replace("# ", "").strip()
            item_status = "todo"

            for line in lines[1:10]:
                if line.startswith("**Status:**"):
                    item_status = line.split("**Status:**")[1].strip()
                    break

            # Filter by status if requested
            if status and item_status != status:
                continue

            todos.append({
                "id": file_path.stem,
                "title": title,
                "status": item_status,
                "file": str(file_path)})
        except Exception as e:
            logger.error(f"Error parsing todo file {file_path}: {e}")
            continue

    if not todos:
        return (
            f"No todos found with status '{status}'."
            if status
            else "No todos found."
        )

    # Format output
    output = f"## Todos ({len(todos)} items)\n\n"

    for todo in todos:
        status_emoji = {
            "todo": "📝",
            "in_progress": "🔄",
            "done": "✅"}.get(todo["status"], "❓")

        output += f"{status_emoji} **{todo['title']}** ({todo['status']})\n"
        output += f"   ID: `{todo['id']}`\n"
        output += f"   File: `{todo['file']}`\n\n"

    return output


def update_todo(
    todo_id: Annotated[str, "ID of the todo to update"],
    title: Annotated[str | None, "New title"] = None,
    description: Annotated[str | None, "New description"] = None,
    status: Annotated[
        str | None, "New status: todo, in_progress, or done"
    ] = None,
    todo_path: str = "./sharedtodos/",
) -> str:
    """Update an existing todo item.

    Updates one or more fields of a todo item. The Markdown file is updated
    accordingly.

    Args:
        todo_id: ID of the todo to update
        title: New title (optional)
        description: New description (optional)
        status: New status (optional)
        todo_path: Path to todo directory

    Returns:
        Success message
    """
    todo_dir = Path(todo_path)
    todo_file = todo_dir / f"{todo_id}.md"

    if not todo_file.exists():
        return f"Error: Todo '{todo_id}' not found."

    # Read current content
    content = todo_file.read_text()
    lines = content.split("\n")

    # Parse current values
    current_title = lines[0].replace("# ", "").strip()
    current_status = "todo"
    current_description = ""
    created_at = ""

    for i, line in enumerate(lines):
        if line.startswith("**Status:**"):
            current_status = line.split("**Status:**")[1].strip()
        elif line.startswith("**Created:**"):
            created_at = line.split("**Created:**")[1].strip()
        elif line.startswith("## Description"):
            # Extract description
            desc_lines = []
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("## Notes"):
                    break
                desc_lines.append(lines[j])
            current_description = "\n".join(desc_lines).strip()
            break

    # Update values
    new_title = title or current_title
    new_status = status or current_status
    new_description = (
        description if description is not None else current_description
    )
    timestamp = datetime.now().isoformat()

    # Build updated content
    new_content = f"""# {new_title}

**Status:** {new_status}  
**Created:** {created_at}  
**Updated:** {timestamp}  
{f"**Completed:** {timestamp}  " if new_status == "done" else ""}

## Description

{new_description}

## Notes

<!-- Add notes here -->
"""

    todo_file.write_text(new_content)
    logger.info(f"Updated todo: {todo_id}")

    changes = []
    if title:
        changes.append(f"title to '{title}'")
    if status:
        changes.append(f"status to '{status}'")
    if description is not None:
        changes.append("description")

    return f"Updated todo '{todo_id}': {', '.join(changes)}"


def complete_todo(
    todo_id: Annotated[str, "ID of the todo to complete"],
    todo_path: str = "./sharedtodos/",
) -> str:
    """Mark a todo as completed.

    Updates the todo status to 'done' and adds a completion timestamp.

    Args:
        todo_id: ID of the todo to complete
        todo_path: Path to todo directory

    Returns:
        Success message
    """
    return update_todo(
        todo_id=todo_id,
        status="done",
        todo_path=todo_path,
    )
