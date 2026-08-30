"""Tool to create new files.

File creation is delegated to the shared :func:`berg_agents.tools._io._atomic_write`
helper, which centralizes parent-directory creation and atomic writes.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil

from ._io import FileObject

from berg_agents.tools._io import _atomic_write, _normalize_target
from langchain.tools import BaseTool, tool
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class NewFileArgs(BaseModel):
    """Arguments for creating a new file.

    Attributes:
        file_path: The full path, including the filename, where the new file should be created.
        content: The content to be written into the new file.
    """

    file_path: str = Field(
        ...,
        description="The full path, including the filename, where the new file should be created.",
    )
    content: str = Field(
        ..., description="The content to be written into the new file."
    )


def make_new_file_tool(root_dir: Path) -> BaseTool:
    """Create a ``new-file`` tool bound to ``root_dir``.

    The root directory is captured in the closure at construction time so the
    tool is a plain :func:`@tool`-decorated function (no custom ``BaseTool``
    subclass fields), which is how recent langchain-core expects tools to be
    registered.

    :param root_dir: The root directory for file operations.
    :return: A LangChain tool that creates new files.
    """
    root = Path(root_dir).expanduser().resolve()

    @tool(
        "new-file",
        args_schema=NewFileArgs,
        response_format="content_and_artifact",
        description=(
            "Create a new file with the given content. "
            "Use this when the user asks to create a file that does not exist yet. "
            "Pass the path relative to the project root."
        ),
    )
    def new_file(
        file_path: str, content: str, overwrite: bool = False
    ) -> tuple[str, FileObject]:
        """Create a new file at the specified path with the given content.

        File creation is delegated to :func:`berg_agents.tools._io._atomic_write`,
        which centralizes atomic writes and parent-directory creation.

        :param file_path: The path where the new file should be created.
        :param content: The content to be written into the new file.
        :param overwrite: Whether to overwrite the file if it already exists.
        :return: A tuple containing a message and a FileObject.
        """
        if not file_path:
            return (
                "❌ Error: 'file_path' cannot be empty.",
                FileObject(path=Path(), contents="", status="error"),
            )

        # The model is told to use the "/workspace" mount, which maps to the
        # project root. Rebase absolute/virtual paths under *root* so writes
        # stay inside the project instead of escaping to the host filesystem
        # (this previously caused PermissionError on "/workspace").
        full_path = _normalize_target(root / file_path, root)

        try:  # ruff: ignore[too-many-statements-in-try-clause]
            # Create a backup before overwriting if the file already exists.
            backup_status = "no_backup"
            if full_path.exists() and overwrite:
                backup_path = full_path.with_suffix(full_path.suffix + ".bak")
                try:
                    shutil.copy(full_path, backup_path)
                    backup_status = "backup_created"
                    log.info(f"Backup created for overwrite: {backup_path}")
                except Exception as e:
                    backup_status = "backup_failed"
                    log.exception(
                        f"Failed to create backup for {full_path} during overwrite: {e}"  # ruff: ignore[verbose-log-message]
                    )

            # Delegate actual file creation to the shared helper, which
            # creates missing parent directories and writes atomically.
            _atomic_write(full_path, content)

            message = f"✅ Successfully created {full_path}"
            if backup_status == "backup_failed":
                message += " (⚠️ Backup failed!)"
            elif backup_status == "backup_created":
                message += " (Original backed up)"

            return (
                message,
                FileObject(path=full_path, contents=content, status="created"),
            )
        except Exception as e:
            log.exception(f"Error creating file {full_path}: ")
            return (
                f"❌ Error creating file: {e}",
                FileObject(path=full_path, contents="", status="error"),
            )

    return new_file
