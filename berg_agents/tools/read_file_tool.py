"""Tool to read files."""

from __future__ import annotations

from pathlib import Path

from berg_agents.tools._io import _normalize_target
from langchain.tools import tool
from pydantic import BaseModel, Field

class ReadFileArgs(BaseModel):
    """Arguments for reading a file.

    Attributes:
        file_path: Path to the file to read, relative to the project root.
        offset: Line number to start reading from (1-indexed).
        limit: Maximum number of lines to read.
    """

    file_path: str = Field(
        ...,
        description="Path to the file to read, relative to the project root.",
    )
    offset: int = Field(
        default=0,
        description="Line number to start reading from (1-indexed).",
    )
    limit: int | None = Field(
        default=None,
        description="Maximum number of lines to read.",
    )


@tool(
    args_schema=ReadFileArgs,
    parse_docstring=True,
    description="Read a file from the project and return its text content.",
)
def read_file(
    file_path: str,
    offset: int = 0,
    limit: int | None = None,
    root_dir: Path | None = None,
) -> str:
    """Read a file from the project and return its text content.

    Use this whenever the user asks to inspect, summarize, or review a file.
    Pass the path relative to the project root.

    :param file_path: Path to the file to read, relative to the project root.
    :param offset: Line number to start reading from (1-indexed).
    :param limit: Maximum number of lines to read.
    :param root_dir: The root directory of the project.
    """
    if root_dir is None:
        root_dir = Path.cwd()

    if not file_path:
        return "❌ Error: 'file_path' cannot be empty."

    full_path = _normalize_target(file_path, root_dir)

    if not full_path.exists():
        return f"❌ Error: File not found at {full_path}"

    if not full_path.is_file():
        return f"❌ Error: Path exists but is not a file: {full_path}"

    try:
        content = full_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        start = max(0, offset - 1)
        end = None if limit is None else start + limit
        snippet = "\n".join(lines[start:end])
        return f"Content of {file_path}:\n\n---\n{snippet}\n---"
    except Exception as e:
        return f"❌ Error reading file: {e}"
