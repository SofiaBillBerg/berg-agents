"""Low-level, synchronous file-system helpers and shared artifacts.

This module is the private home of the package's atomic file-write helper,
the small set of pure, stateless file helpers the agent uses to template
files, and the :class:`FileObject` artifact shared by the file tools.  It
was extracted from the legacy :mod:`berg_agents.file_generator` module
(which has been removed) so that consumers (CLI, tools, tests) share a
single implementation.

All functions are stateless, return a :class:`pathlib.Path` instance
pointing to the created file, and raise ``CodeAgentError`` (defined in
:mod:`berg_agents.exceptions`) on failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from berg_agents.exceptions import CodeAgentError

#: Optional Jupyter notebook dependency; ``None`` when unavailable.
nbformat: ModuleType | None
try:  # Optional dependency - used only for the notebook path.
    import nbformat
except Exception as e:  # pragma: no cover - handled at runtime
    # noinspection PyGlobalVariableRedeclarationInNotebook
    print(f"Warning: nbformat not available ({e})")
    # noinspection PyGlobalVariableRedeclarationInNotebook
    nbformat = None

__all__ = ["FileObject", "_atomic_write", "create_from_template"]


@dataclass
class FileObject:
    """Artifact representing a file.

    Attributes:
        path: Path to the file, relative to the project root.
        contents: Content of the file.
        status: Status of the file, either "success" or "error".
    """

    path: Path
    contents: str
    status: str = "success"


def _normalize_target(
    target: str | Path, root: str | Path | None = None
) -> Path:
    """Rebase a write target so it stays safely inside the project root.

    The agent runtime advertises the project as the ``/workspace`` mount, but
    the real filesystem root is *root* (defaults to the current working
    directory). Strip a leading ``/workspace`` prefix (and any redundant
    directory segment that matches *root*'s name, e.g. a doubled ``berg_agents``)
    so absolute/virtual paths do not escape into the host filesystem (which
    previously caused ``PermissionError`` on ``/workspace``).
    """
    root_path = (
        Path(root).expanduser().resolve() if root else Path.cwd().resolve()
    )
    raw = Path(target).expanduser()

    if raw.is_absolute():
        # Already inside the project root -> use as-is (do not re-rebase).
        try:
            raw.relative_to(root_path)
            return raw.resolve()
        except ValueError:
            pass
        # Virtual "/workspace" mount -> rebase onto the project root, dropping a
        # redundant leading directory that matches the project name (e.g. a
        # doubled "berg_agents").
        if str(raw).startswith("/workspace"):
            rel = raw.relative_to("/workspace")
            parts = rel.parts
            if parts and parts[0] == root_path.name:
                rel = Path(*parts[1:])
            return (root_path / rel).resolve()
        # Any other absolute path -> clamp under root, dropping a redundant
        # leading segment that matches the project directory name.
        rel = raw.relative_to(raw.anchor)
        parts = rel.parts
        if parts and parts[0] == root_path.name:
            rel = Path(*parts[1:])
        return (root_path / rel).resolve()

    # Relative path -> join onto the project root.
    return (root_path / raw).resolve()


def _atomic_write(
    target: Path | str,
    content: str,
    *,
    mode: str = "w",
    encoding: str = "utf-8",
) -> Path:
    """Write *content* to *target* atomically.

    The function creates any missing parent directories, writes the
    content to a temporary file first, and then atomically moves the
    temporary file to ``target``.  This prevents partial writes if the
    process is interrupted.

    :param target: Destination file path.
    :param content: Text to write.
    :param mode: File mode - defaults to ``"w"``.
    :param encoding: Text encoding - defaults to ``"utf-8"``.
    :return: The absolute path of the written file.
    :raises CodeAgentError: If *target* is a directory or the write fails.
    """
    target = Path(target).expanduser().resolve()
    if target.is_dir():
        raise CodeAgentError(f"Cannot write to a directory: {target!s}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        with tmp.open(mode, encoding=encoding) as fp:
            fp.write(content)
        tmp.replace(target)
        return target
    except OSError as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(f"Failed to write file {target!s}: {exc}") from exc


def create_from_template(
    template_root_dir: Path,
    dest_root_dir: Path,
    *,
    replace_vars: dict | None = None,
) -> Path:
    """Create *dest_path* by copying *template_path*.

    ``replace_vars`` may contain placeholder keys that will be replaced
    in the template text using :meth:`str.format`.  The function
    returns the absolute :class:`Path` to the created file.

    :param template_root_dir: Path to the template file.
    :param dest_root_dir: Path to the destination file to create.
    :param replace_vars: Optional dict of placeholders to replace.
    :return: The absolute path of the created file.
    """
    template_path = Path(template_root_dir).expanduser().resolve()
    dest_path = Path(dest_root_dir).expanduser().resolve()
    if not template_path.is_file():
        raise CodeAgentError(f"Template file {template_path!s} does not exist")
    try:
        text = template_path.read_text(encoding="utf-8")
        if replace_vars:
            text = text.format(**replace_vars)
        return _atomic_write(dest_path, text)
    except Exception as exc:  # pragma: no cover - exercised via tests
        raise CodeAgentError(
            f"Failed to create {dest_path!s} from template {template_path!s}: {exc}"
        ) from exc
