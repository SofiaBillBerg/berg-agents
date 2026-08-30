"""Tool for editing existing files."""

from __future__ import annotations

import logging
from pathlib import Path

from berg_agents.tools._io import _atomic_write, _normalize_target
from langchain.tools import tool
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class EditFileArgs(BaseModel):
    """Arguments for editing a file.

    Attributes:
        file_path: Path to the file to edit, relative to the project root.
        new_content: New content for the file.
        mode: Edit mode: replace, append, or patch.
    """

    file_path: str = Field(
        ...,
        description="Path to the file to edit, relative to the project root.",
    )
    new_content: str = Field(..., description="New content for the file.")
    mode: str = Field(
        "replace", description="Edit mode: replace, append, or patch."
    )


@tool(
    args_schema=EditFileArgs,
    parse_docstring=True,
    description="Edit an existing file by replacing, appending, or patching its content.",
)
def edit_file(
    file_path: str,
    new_content: str,
    mode: str = "replace",
    root_dir: Path | None = None,
) -> str:
    """Edit an existing file by replacing, appending, or patching its content.

    Use this when the user asks to change, edit, update, or append to a file.
    Pass the path relative to the project root.

    :param file_path: Path to the file to edit, relative to the project root.
    :param new_content: New content for the file.
    :param mode: Edit mode: replace, append, or patch.
    :param root_dir: Root directory of the project.
    :return: Success or error message.
    """
    if root_dir is None:
        root_dir = Path.cwd()

    full_path = _normalize_target(file_path, root_dir)

    if not full_path.exists():
        return f"❌ File not found: {full_path}"

    try:  # ruff: ignore[too-many-statements-in-try-clause]
        if mode == "replace":
            _atomic_write(full_path, new_content)
        elif mode == "append":
            original = full_path.read_text(encoding="utf-8")
            _atomic_write(full_path, original + new_content)
        elif mode == "patch":
            original = full_path.read_text(encoding="utf-8")
            start_marker = "<!-- AUTOGEN START -->"
            end_marker = "<!-- AUTOGEN END -->"
            if start_marker in original and end_marker in original:
                pre, rest = original.split(start_marker, 1)
                _, post = rest.split(end_marker, 1)
                new_full = (
                    pre
                    + start_marker
                    + "\n"
                    + new_content
                    + "\n"
                    + end_marker
                    + post
                )
            else:
                new_full = original + "\n" + new_content
            _atomic_write(full_path, new_full)
        else:
            return f"❌ Unknown mode: {mode}"

        return f"✅ Successfully {mode} {full_path}"
    except Exception as e:
        log.exception(
            f"Error editing file {full_path}: {e}"  # ruff: ignore[verbose-log-message]
        )  # ruff: ignore[verbose-log-message]
        return f"❌ Error editing file: {e}"
