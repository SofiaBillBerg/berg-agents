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

import logging

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any


logger = logging.getLogger(__name__)


def _parse_subtasks(lines: list[str]) -> list[dict[str, Any]]:
    """Parse the ``## Subtasks`` checklist section of a todo file.

    Accepts ``- [ ] text`` (open) and ``- [x]`` / ``- [X]`` (done).
    Anything else in the section is ignored, so hand edits stay safe.

    :param lines: Todo file split into lines.
    :return: List of ``{"index", "text", "done"}`` in file order.
    """
    items: list[dict[str, Any]] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Subtasks"):
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue
        lowered = stripped.lower()
        if lowered.startswith("- [x]"):
            items.append({
                "index": len(items),
                "text": stripped[5:].strip(),
                "done": True})
        elif lowered.startswith("- [ ]"):
            items.append({
                "index": len(items),
                "text": stripped[5:].strip(),
                "done": False})
    return items


def _render_subtasks(items: list[dict[str, Any]]) -> str:
    """Render subtask items back to checklist Markdown lines."""
    rendered = []
    for item in items:
        mark = "x" if item.get("done") else " "
        rendered.append(f"- [{mark}] {item.get('text', '')}")
    return "\n".join(rendered)


def _split_sections(content: str) -> tuple[str, str, str]:
    """Split a todo file into description body, subtask items stay coded.

    Returns ``(description, notes, subtask_items)`` where description is
    the raw text between ``## Description`` and the next ``##`` header
    (or end), and notes likewise for ``## Notes``. Subtasks come back
    as parsed items so rewrites (status changes) never drop them.

    :param content: Full todo Markdown file text.
    :return: Tuple of description text, notes text, subtask items.
    """
    lines = content.split("\n")
    description_lines: list[str] = []
    notes_lines: list[str] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("## Description"):
            current = description_lines
            continue
        elif line.startswith("## Notes"):
            current = notes_lines
            continue
        elif line.startswith("## Subtasks"):
            current = None
            continue
        elif line.startswith("## "):
            current = None
            continue
        elif line.startswith("# "):
            continue
        elif line.startswith("**") and "**:" in line:
            continue
        if current is not None:
            current.append(line)
    return (
        "\n".join(description_lines).strip(),
        "\n".join(notes_lines).strip(),
        _parse_subtasks(lines),
    )


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

## Subtasks

<!-- Add subtasks as - [ ] lines -->

## Notes

<!-- Add notes here -->
"""

    todo_file.write_text(content)
    logger.info(f"Created todo: {todo_id}")

    return f"Created todo '{title}' with ID: {todo_id}\nFile: {todo_file}"


def list_todo_items(
    status: str | None = None,
    todo_path: str = "./sharedtodos/",
) -> list[dict[str, str]]:
    """List todo items as structured data (for API/UI surfaces).

    Uses the same Markdown parsing rules as :func:`list_todos` but
    returns mappings instead of formatted text.

    Args:
        status: Optional status filter (todo, in_progress, done).
        todo_path: Path to todo directory.

    Returns:
        List of ``{"id", "title", "status", "file"}`` mappings.
    """
    todo_dir = Path(todo_path)

    if not todo_dir.exists():
        return []

    items = []
    for file_path in sorted(todo_dir.glob("*.md")):
        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.split("\n")
            if not lines or not lines[0].startswith("#"):
                continue

            # Parse title and status
            title = lines[0].replace("# ", "").strip()
            item_status = "todo"

            for line in lines[1:10]:
                if line.startswith("**Status:**"):
                    item_status = line.split("**Status:**")[1].strip()
                    break

            # Extract description via the shared splitter (also parses
            # subtasks so one parse rule serves every reader).
            content = file_path.read_text(encoding="utf-8")
            description, _, subtasks = _split_sections(content)

            # Filter by status if requested
            if status and item_status != status:
                continue

            items.append({
                "id": file_path.stem,
                "title": title,
                "status": item_status,
                "description": description,
                "subtasks": subtasks,
                "file": str(file_path)})
        except OSError as e:
            logger.error(f"Error parsing todo file {file_path}: {e}")
            continue

    return items


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


def delete_todo(
    todo_id: Annotated[str, "ID of the todo to delete"],
    todo_path: str = "./sharedtodos/",
) -> str:
    """Delete a todo item.

    Removes the todo Markdown file permanently.

    Args:
        todo_id: ID of the todo to delete
        todo_path: Path to todo directory

    Returns:
        Success message
    """
    todo_dir = Path(todo_path)
    todo_file = todo_dir / f"{todo_id}.md"

    if not todo_file.exists():
        return f"Error: Todo '{todo_id}' not found."

    try:
        todo_file.unlink()
    except OSError as e:
        logger.error(f"Error deleting todo file {todo_file}: {e}")
        return f"Error: Could not delete todo '{todo_id}': {e}"

    logger.info(f"Deleted todo: {todo_id}")

    return f"Deleted todo '{todo_id}'"


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

    # Parse current values via the shared splitter so subtasks and
    # notes survive rewrites (status toggles must never drop them).
    current_title = lines[0].replace("# ", "").strip()
    current_status = "todo"
    created_at = ""

    for line in lines:
        if line.startswith("**Status:**"):
            current_status = line.split("**Status:**")[1].strip()
        elif line.startswith("**Created:**"):
            created_at = line.split("**Created:**")[1].strip()

    current_description, current_notes, subtasks = _split_sections(content)

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

## Subtasks

{_render_subtasks(subtasks)}

## Notes

{current_notes if current_notes else "<!-- Add notes here -->"}
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


def _load_subtasks(
    todo_id: str, todo_path: str
) -> tuple[Path, list[str], list[dict[str, Any]]] | str:
    """Load a todo file for subtask edits.

    :param todo_id: Todo identifier.
    :param todo_path: Path to todo directory.
    :return: ``(todo_file, lines, subtasks)`` or an error message.
    """
    todo_file = Path(todo_path) / f"{todo_id}.md"
    if not todo_file.exists():
        return f"Error: Todo '{todo_id}' not found."
    try:
        content = todo_file.read_text(encoding="utf-8")
    except OSError as e:
        return f"Error: Could not read todo '{todo_id}': {e}"
    lines = content.split("\n")
    return todo_file, lines, _parse_subtasks(lines)


def _write_subtasks(
    todo_file: Path, lines: list[str], subtasks: list[dict[str, Any]]
) -> None:
    """Rewrite a todo file's ``## Subtasks`` section in place.

    Keeps every other section byte-identical (only the checklist lines
    between ``## Subtasks`` and the next ``##`` header change). Files
    without the section gain one before ``## Notes`` (or at the end).

    :param todo_file: Todo Markdown file to update.
    :param lines: Current file lines.
    :param subtasks: New subtask items.
    """
    rendered = _render_subtasks(subtasks).split("\n") if subtasks else []
    out: list[str] = []
    in_section = False
    section_seen = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Subtasks"):
            section_seen = True
            in_section = True
            out.append(line)
            out.extend(rendered)
            continue
        if in_section and stripped.startswith("## "):
            in_section = False
        if in_section:
            continue
        out.append(line)
    if not section_seen:
        block = ["", "## Subtasks", "", *rendered]
        insert_at = next(
            (i for i, line in enumerate(out) if line.startswith("## Notes")),
            len(out),
        )
        out[insert_at:insert_at] = block
    todo_file.write_text("\n".join(out), encoding="utf-8")


def add_subtask(
    todo_id: Annotated[str, "ID of the todo to extend"],
    text: Annotated[str, "Subtask text"],
    todo_path: str = "./sharedtodos/",
) -> str:
    """Add a subtask checklist item to a todo.

    Appends ``- [ ] <text>`` to the todo's ``## Subtasks`` section,
    creating the section when missing.

    Args:
        todo_id: ID of the todo to extend
        text: Subtask text (must not be blank)
        todo_path: Path to todo directory

    Returns:
        Success message with the subtask index
    """
    if not text.strip():
        return "Error: Subtask text must not be blank."
    loaded = _load_subtasks(todo_id, todo_path)
    if isinstance(loaded, str):
        return loaded
    todo_file, lines, subtasks = loaded
    subtasks.append({
        "index": len(subtasks),
        "text": text.strip(),
        "done": False})
    try:
        _write_subtasks(todo_file, lines, subtasks)
    except OSError as e:
        return f"Error: Could not write todo '{todo_id}': {e}"
    logger.info(f"Added subtask to {todo_id}: {text.strip()}")
    return f"Added subtask #{len(subtasks) - 1} to '{todo_id}': {text.strip()}"


def set_subtask_done(
    todo_id: Annotated[str, "ID of the todo"],
    index: Annotated[int, "Subtask index (file order, from 0)"],
    done: Annotated[bool, "True to check, False to uncheck"] = True,
    todo_path: str = "./sharedtodos/",
) -> str:
    """Check or uncheck a subtask by index.

    Args:
        todo_id: ID of the todo
        index: Subtask index in file order (from 0)
        done: True to check off, False to reopen
        todo_path: Path to todo directory

    Returns:
        Success message
    """
    loaded = _load_subtasks(todo_id, todo_path)
    if isinstance(loaded, str):
        return loaded
    todo_file, lines, subtasks = loaded
    if index < 0 or index >= len(subtasks):
        return f"Error: Subtask #{index} not found in '{todo_id}'."
    subtasks[index]["done"] = done
    try:
        _write_subtasks(todo_file, lines, subtasks)
    except OSError as e:
        return f"Error: Could not write todo '{todo_id}': {e}"
    state = "done" if done else "reopened"
    return f"Marked subtask #{index} '{subtasks[index]['text']}' as {state}."


def delete_subtask(
    todo_id: Annotated[str, "ID of the todo"],
    index: Annotated[int, "Subtask index (file order, from 0)"],
    todo_path: str = "./sharedtodos/",
) -> str:
    """Delete a subtask by index (later items shift down).

    Args:
        todo_id: ID of the todo
        index: Subtask index in file order (from 0)
        todo_path: Path to todo directory

    Returns:
        Success message
    """
    loaded = _load_subtasks(todo_id, todo_path)
    if isinstance(loaded, str):
        return loaded
    todo_file, lines, subtasks = loaded
    if index < 0 or index >= len(subtasks):
        return f"Error: Subtask #{index} not found in '{todo_id}'."
    removed = subtasks.pop(index)
    for position, item in enumerate(subtasks):
        item["index"] = position
    try:
        _write_subtasks(todo_file, lines, subtasks)
    except OSError as e:
        return f"Error: Could not write todo '{todo_id}': {e}"
    logger.info(f"Deleted subtask #{index} from {todo_id}")
    return f"Deleted subtask #{index} '{removed['text']}' from '{todo_id}'."


def rename_subtask(
    todo_id: Annotated[str, "ID of the todo"],
    index: Annotated[int, "Subtask index (file order, from 0)"],
    text: Annotated[str, "New subtask text"],
    todo_path: str = "./sharedtodos/",
) -> str:
    """Rename a subtask's text (user or agent may correct wording).

    Args:
        todo_id: ID of the todo
        index: Subtask index in file order (from 0)
        text: Replacement text (must not be blank)
        todo_path: Path to todo directory

    Returns:
        Success message
    """
    if not text.strip():
        return "Error: Subtask text must not be blank."
    loaded = _load_subtasks(todo_id, todo_path)
    if isinstance(loaded, str):
        return loaded
    todo_file, lines, subtasks = loaded
    if index < 0 or index >= len(subtasks):
        return f"Error: Subtask #{index} not found in '{todo_id}'."
    previous = subtasks[index]["text"]
    subtasks[index]["text"] = text.strip()
    try:
        _write_subtasks(todo_file, lines, subtasks)
    except OSError as e:
        return f"Error: Could not write todo '{todo_id}': {e}"
    logger.info(f"Renamed subtask #{index} on {todo_id}")
    return (
        f"Renamed subtask #{index} on '{todo_id}' "
        f"from '{previous}' to '{text.strip()}'."
    )
