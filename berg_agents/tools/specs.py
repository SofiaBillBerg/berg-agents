#
# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.
#

# The workspace tools as ToolSpecs -- and the ONE place their signatures live.
# agents/implementation.py builds an agent at module scope while the
# orchestrator is still loading, so factory was only partially initialised.
#
# These functions are pure filesystem operations. Nothing here knows about


from __future__ import annotations

from pathlib import Path

from berg_agents.tools.tool_spec import ToolSpec, make_tool_spec
from berg_agents.tools._io import _atomic_write, _normalize_target


def _resolve_root(root_dir: str | Path) -> Path:
    return Path(root_dir).expanduser().resolve()





def create_tools(root_dir: str | Path = ".") -> list[ToolSpec]:  # ruff: ignore[complex-structure]
    """Return the default tool set as ToolSpecs.

    Wraps file ops with *root_dir* captured via closure so the model only
    sees ``file_path`` / ``content`` - not ``root_dir``.

    :param root_dir: Root directory file tools are bound to.
    :return: List of ToolSpec instances.
    """
    root = _resolve_root(root_dir)

    def _read(file_path: str) -> str:
        """Read a file relative to the workspace root.

        Returns a helpful message instead of raising when the
        path is a directory or does not exist, so the model
        can recover (e.g. by calling ``list_files``) instead
        of derailing into an error loop.

        :param file_path: Path to the file, may be /workspace-prefixed.
        """
        target = _normalize_target(file_path, root)
        if target.is_dir():
            return (
                f"{file_path} is a directory, not a file. "
                f"Call list_files with file_path={file_path!r} "
                f"to see its contents."
            )
        if not target.exists():
            return (
                f"File not found: {file_path}. "
                f"Call list_files on the parent directory to see "
                f"what exists."
            )
        try:
            return target.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Could not read {file_path}: {exc}"
        except UnicodeDecodeError:
            return f"Could not read {file_path}: not a UTF-8 text file."

    def _edit(file_path: str, content: str) -> str:
        """Edit an existing file (replace contents).

        :param file_path: Path to the file.
        :param content: New file contents.
        """
        target = _normalize_target(file_path, root)
        _atomic_write(target, content)
        return f"Edited {file_path}"

    def _write(file_path: str, content: str) -> str:
        """Create or overwrite a file.

        :param file_path: Path to the file to create.
        :param content: File contents.
        """
        target = _normalize_target(file_path, root)
        _atomic_write(target, content)
        return f"Wrote {file_path}"

    def _patch(file_path: str, old_text: str, new_text: str) -> str:
        """Replace one block of text inside an existing file.

        Surgical alternative to rewriting the whole file: only the
        first occurrence of ``old_text`` is replaced. Fails with
        guidance (instead of guessing) when the file is missing or
        the block is not found verbatim.

        :param file_path: Path to the file to patch.
        :param old_text: Exact text block to replace (verbatim).
        :param new_text: Replacement text.
        """
        target = _normalize_target(file_path, root)
        if target.is_dir():
            return (
                f"{file_path} is a directory, not a file. "
                f"Call list_files with file_path={file_path!r} "
                f"to see its contents."
            )
        if not target.exists():
            return (
                f"File not found: {file_path}. "
                f"Call list_files on the parent directory to see "
                f"what exists."
            )
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Could not read {file_path}: {exc}"
        except UnicodeDecodeError:
            return f"Could not read {file_path}: not a UTF-8 text file."
        if old_text not in text:
            return (
                f"Block not found verbatim in {file_path}. "
                f"Call read_file first and copy the exact text, "
                f"whitespace included."
            )
        remaining = text.count(old_text) - 1
        _atomic_write(target, text.replace(old_text, new_text, 1))
        note = (
            f" ({remaining} identical block(s) left untouched)"
            if remaining
            else ""
        )
        return f"Patched {file_path}{note}"

    def _list(file_path: str = ".") -> str:
        """List files and subdirectories in a workspace directory.

        Use this to explore the project layout before reading
        files - never guess at paths. Directories end with "/".
        Results are sorted, directories first, capped at 200
        entries to keep the context small.

        :param file_path: Directory to list, relative to the
            workspace root (default: the root itself).
        """
        target = _normalize_target(file_path, root)
        if not target.exists():
            return (
                f"Directory not found: {file_path}. "
                f"Call list_files with file_path='.' to start "
                f"from the workspace root."
            )
        if not target.is_dir():
            return (
                f"{file_path} is a file, not a directory. "
                f"Call read_file to see its contents."
            )
        try:
            entries = sorted(
                target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
        except OSError as exc:
            return f"Could not list {file_path}: {exc}"
        lines = [f"{p.name}/" if p.is_dir() else p.name for p in entries[:200]]
        extra = (
            f"\n... and {len(entries) - 200} more (listing truncated)"
            if len(entries) > 200
            else ""
        )
        return "\n".join(lines) + extra if lines else "(empty directory)"

    def _bash(command: str, timeout: int = 30) -> str:
        """Run a shell command in the workspace root.

        Use this to run tests, builds, linters, or inspect the
        system (e.g. ``pytest -q``, ``ls``, ``python --version``).
        There is no other shell/terminal tool - this is it.

        Safety: commands run with ``cwd`` bound to the workspace
        root, a timeout (default 30s, capped at 120s), and output
        truncated at 8000 characters. Every invocation is logged.

        :param command: Shell command to run (via ``bash -c``).
        :param timeout: Seconds before the command is killed.
        """
        import logging
        import subprocess

        try:
            clamped = max(1, min(int(timeout), 120))
        except (TypeError, ValueError):
            clamped = 30
        logging.getLogger(__name__).warning("bash tool: %s", command)
        try:
            proc = subprocess.run(
                command,
                check=False,
                shell=True,
                executable="/bin/bash",
                cwd=root,
                capture_output=True,
                text=True,
                timeout=clamped,
            )
        except subprocess.TimeoutExpired:
            return (
                f"Command timed out after {clamped}s and was killed: {command}"
            )
        except OSError as exc:
            return f"Could not run command: {exc}"
        combined = (proc.stdout or "") + (
            f"\n[stderr]\n{proc.stderr}" if proc.stderr else ""
        )
        if len(combined) > 8000:
            combined = (
                combined[:8000] + f"\n... output truncated "
                f"({len(combined)} chars total)"
            )
        return f"[exit {proc.returncode}]\n{combined}".strip()

    def _search(pattern: str, directory: str = ".") -> str:
        """Search file contents under a workspace directory.

        Recursive literal-match grep over text files. Use this to
        find references, definitions, or error strings instead of
        guessing file paths. Binary files, hidden directories
        (``.git``, ``node_modules``, ``__pycache__``, ``.venv``),
        and files over 1MB are skipped. Results capped at 50 hits.

        :param pattern: Literal text to search for (not a regex).
        :param directory: Where to search, relative to the
            workspace root (default: the root itself).
        """
        base = _normalize_target(directory, root)
        if not base.exists():
            return (
                f"Directory not found: {directory}. "
                f"Call list_files with file_path='.' to start "
                f"from the workspace root."
            )
        if not base.is_dir():
            return (
                f"{directory} is a file, not a directory. "
                f"Call read_file to see its contents."
            )
        skip_dirs = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            ".next",
            "dist",
            ".turbo"}
        hits: list[str] = []
        scanned = 0
        for path in sorted(base.rglob("*")):
            if len(hits) >= 50:
                break
            if any(part in skip_dirs for part in path.parts):
                continue
            if not path.is_file():
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
            except OSError:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            scanned += 1
            if scanned > 2000:
                break
            for i, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    rel = path.relative_to(root)
                    hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(hits) >= 50:
                        break
        if not hits:
            return f"No matches for {pattern!r} under {directory}."
        extra = (
            "\n... and more (results truncated at 50)"
            if len(hits) >= 50
            else ""
        )
        return "\n".join(hits) + extra

    return [
        make_tool_spec(_list, name="list_files", risk_class="low"),  # type: ignore[arg-type]
        make_tool_spec(_read, name="read_file", risk_class="low"),  # type: ignore[arg-type]
        make_tool_spec(_search, name="search_code", risk_class="low"),  # type: ignore[arg-type]
        make_tool_spec(_bash, name="bash", risk_class="high"),  # type: ignore[arg-type]
        make_tool_spec(_edit, name="edit_file", risk_class="high"),  # type: ignore[arg-type]
        make_tool_spec(_patch, name="patch_file", risk_class="high"),  # type: ignore[arg-type]
        make_tool_spec(_write, name="write_file", risk_class="high"),  # type: ignore[arg-type]
    ]
