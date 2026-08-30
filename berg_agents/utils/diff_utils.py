"""Utility functions for generating diffs between files and content."""

from __future__ import annotations

import difflib
from pathlib import Path

def generate_diff(
    old_content: str,
    new_content: str,
    from_file: str = "original",
    to_file: str = "modified",
) -> str:
    """Generate a unified diff between two strings.

    :param old_content: The original content
    :param new_content: The new content
    :param from_file: Label for the original content
    :param to_file: Label for the modified content

    :return: string containing the unified diff
    """
    diff = difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=from_file,
        tofile=to_file,
    )
    return "".join(diff)


def preview_file_edit(
    file_path: str | Path, new_content: str, create_if_missing: bool = False
) -> tuple[str, bool]:
    """Generate a preview of file changes without modifying the file.

    :param file_path: Path to the file being edited
    :param new_content: The new content to preview
    :param create_if_missing: If True, treat non-existent files as empty

    :return: A tuple of (diff_string, file_exists) where:
        - diff_string is the unified diff
        - file_exists indicates if the original file existed
    """
    path = Path(file_path)

    if path.exists():
        old_content = path.read_text(encoding="utf-8")
        file_exists = True
    elif create_if_missing:
        old_content = ""
        file_exists = False
    else:
        raise FileNotFoundError(f"File not found: {file_path}")

    diff = generate_diff(
        old_content, new_content, str(path), f"(proposed) {path}"
    )
    return diff, file_exists


def apply_edit(file_path: str | Path, content: str) -> None:
    """Apply changes to a file.

    :param file_path: Path to the file to modify
    :param content: The new content
    :return: None
    :raises OSError: If the file cannot be written
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
