"""Utility functions for generating diffs between files and content."""

#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

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
