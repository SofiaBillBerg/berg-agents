"""Format code tool."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from berg_agents.tools._io import FileObject, _normalize_target
from langchain.tools import BaseTool, tool
from pydantic import BaseModel, Field

class FormatCodeArgs(BaseModel):
    """Args for the format-code tool.

    Attributes:
        file_path: Path to the file to format.
        mode: Mode: auto|python|r
    """

    file_path: str = Field(..., description="Path to the file to format")
    mode: str = Field("auto", description="Mode: auto|python|r")


def make_format_code_tool(root_dir: Path) -> BaseTool:
    """Create a ``format-code`` tool bound to ``root_dir``.

    The root directory is captured in the closure at construction time so the
    tool is a plain :func:`@tool`-decorated function (no custom ``BaseTool``
    subclass fields), which is how recent langchain-core expects tools to be
    registered.

    :param root_dir: The root directory of the project.
    :return: A LangChain tool that formats source files.
    """
    root = Path(root_dir).expanduser().resolve()

    @tool(
        "format-code",
        args_schema=FormatCodeArgs,
        response_format="content_and_artifact",
        description=(
            "Format a source file. For python files, run black and isort if available. "
            "For R files, optionally run styler if available. Returns a FileObject."
        ),
    )
    def format_code(
        file_path: str, mode: str = "auto"
    ) -> tuple[str, FileObject]:
        """Format a source file.

        If the file is a Python file, run black and isort if available.
        If the file is an R file, optionally run styler if available.

        :param file_path: Path to the file to format.
        :param mode: Mode: auto|python|r
        :return: Tuple of (message, FileObject).
        """
        p = _normalize_target(file_path, root)
        if not p.exists():
            return (
                f"❌ File not found: {p}",
                FileObject(path=p, contents="", status="error"),
            )

        ext = p.suffix.lower()
        if mode == "auto":
            if ext == ".py":
                mode = "python"
            elif ext in {".r", ".R"}:
                mode = "r"

        # Delegate formatting to helper functions to reduce complexity
        if mode == "python":
            ok, msg = _format_python(p)
        elif mode == "r":
            ok, msg = _format_r(p)
        else:
            return (
                f"❌ Unknown mode: {mode}",
                FileObject(path=p, contents="", status="error"),
            )

        if not ok:
            return (
                f"❌ Formatting failed: {msg}",
                FileObject(path=p, contents="", status="error"),
            )

        new_contents = p.read_text(encoding="utf-8")
        return (
            f"✅ Formatted {p}",
            FileObject(path=p, contents=new_contents, status="formatted"),
        )

    return format_code


def _format_python(p: Path) -> tuple[bool, str]:
    """Run python formatters (isort, black) if available.

    :param p: Path to the file to format.
    :return: (success, message).
    """
    try:
        if shutil.which("isort"):
            subprocess.run(["isort", str(p)], check=False)
        if shutil.which("black"):
            subprocess.run(["black", str(p)], check=False)
        return True, ""
    except Exception as e:
        return False, str(e)


def _format_r(p: Path) -> tuple[bool, str]:
    """Run R styler via Rscript if available.

    :param p: Path to the file to format.
    :return: (success, message).
    """
    try:
        if shutil.which("Rscript"):
            rcmd = f"styler::style_file('{p!s}')"
            subprocess.run(["Rscript", "-e", rcmd], check=False)
        return True, ""
    except Exception as e:
        return False, str(e)
