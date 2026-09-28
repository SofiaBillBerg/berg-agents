"""Filesystem backend.

This module provides filesystem functionality for BergAgents:

* ``FilesystemBackend`` — maps ``/workspace/...`` virtual paths to a real
  ``root_dir`` on disk with ``virtual_mode`` sandboxing (``..``, ``~``, and
  absolute escapes are blocked).
* ``StateBackend`` — ephemeral in-memory store for agent-internal
  artifacts (``/large_tool_results``, ``/conversation_history``) so they never
  pollute the user's project.
* ``VirtualBackend`` — routes by prefix (``/workspace`` → filesystem,
  everything else → state).
* ``PermissionRule`` + ``evaluate_permissions`` — ordered first-match-wins glob
  rules (``allow``/``deny``/``interrupt``).
* ``make_backend`` / ``make_permissions`` / ``resolve_workspace_paths``
  — constructors and helpers for the backends above.

Only stdlib (pathlib, fnmatch, re).
"""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Route prefix under which the real working directory is mounted.
DEFAULT_WORKSPACE_PREFIX = "/workspace/"

#: Tools provided out of the box by BergAgents, so callers can refer to the
#: same tool names when building permission rules.
FS_BUILTIN_TOOLS: frozenset[str] = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "delete",
        "execute",
        "task",
    }
)

#: Built-in tools that modify state and therefore default to HITL review.
DEFAULT_INTERRUPT_ON: dict[str, bool] = {
    "edit_file": True,
    "write_file": True,
    "delete": True,
    "execute": True,
}


# ---------------------------------------------------------------------------
# Permission rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionRule:
    """A single filesystem permission rule.

    Rules are evaluated in order; first match wins.  Any path that matches no
    rule is ``allow`` (so deny rules must come before the allow-all).

    :param operations: Operations this rule applies to (``read``/``write``).
    :param paths: Glob patterns matched against the validated route-prefixed
        path, e.g. ``/workspace/foo/bar.py``.  ``**`` crosses directories.
    :param mode: ``allow``, ``deny``, or ``interrupt`` (HITL).
    """

    operations: list[str]
    paths: list[str]
    mode: Literal["allow", "deny", "interrupt"]


def _matches_glob(pattern: str, path: str) -> bool:
    """Match *path* against a single glob *pattern*.

    Uses :func:`fnmatch.fnmatch` semantics where ``*`` matches everything
    except ``/`` and ``**`` is treated as ``*`` (fnmatch already crosses
    directories for ``*`` on POSIX).

    :param pattern: Glob pattern (may contain ``*`` and ``**``).
    :param path: Virtual path to test, e.g. ``/workspace/foo/bar.py``.
    :return: True if the pattern matches.
    """
    # Normalize ``**`` to ``*`` for fnmatch — on POSIX ``*`` already crosses
    # ``/`` in fnmatch, so the distinction is moot for our permission paths.
    # We keep ``**`` in stored patterns for readability/compatibility.
    norm = pattern.replace("**", "*")
    return fnmatch.fnmatch(path, norm)


def evaluate_permissions(
    rules: list[PermissionRule],
    operation: str,
    virtual_path: str,
) -> Literal["allow", "deny", "interrupt"]:
    """Evaluate *rules* for *operation* on *virtual_path*.

    First-match-wins.  If no rule matches, returns ``allow``.

    :param rules: Ordered permission rules.
    :param operation: ``read`` or ``write``.
    :param virtual_path: Virtual path, e.g. ``/workspace/foo.py``.
    :return: The matched mode or ``allow``.
    """
    for rule in rules:
        if operation not in rule.operations:
            continue
        for pat in rule.paths:
            if _matches_glob(pat, virtual_path):
                return rule.mode  # type: ignore[return-value]
    return "allow"


def make_permissions(
    *,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
) -> list[PermissionRule]:
    """Return default permission rules.

    deny ``.env``/``secrets`` first, then allow reads, then interrupt writes.

    :param workspace_prefix: Virtual mount point (must start and end with ``/``).
    :return: Ordered list of permission rules.
    """
    wp = workspace_prefix.rstrip("/")  # e.g. "/workspace"
    return [
        PermissionRule(
            operations=["read", "write"],
            paths=[f"{wp}/.env", f"{wp}/**/.env", f"{wp}/secrets/**"],
            mode="deny",
        ),
        PermissionRule(
            operations=["read"],
            paths=[f"{wp}/**"],
            mode="allow",
        ),
        PermissionRule(
            operations=["write"],
            paths=[f"{wp}/**"],
            mode="interrupt",
        ),
    ]


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


class FilesystemBackend:
    """Real-disk backend mounted at a virtual prefix.

    :param root_dir: Real working directory on disk.
    :param virtual_mode: When True (recommended), ``..``, ``~``, and absolute
        paths outside the root are blocked with ``ValueError``.
    """

    def __init__(
        self,
        root_dir: str | Path,
        virtual_mode: bool = True,
    ) -> None:
        """Initialize the backend.

        :param root_dir: Real working directory on disk.
        :param virtual_mode: When True, sandbox escapes with ``ValueError``.
        """
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.virtual_mode = virtual_mode

    def _resolve(self, virtual_path: str) -> Path:
        """Resolve *virtual_path* (e.g. ``/workspace/foo/bar.py``) to a real path.

        :param virtual_path: Virtual path under the workspace prefix.
        :return: Resolved real path under ``root_dir``.
        :raises ValueError: If the path escapes the workspace when
            ``virtual_mode`` is True.
        """
        # Strip the prefix — caller (Composite) already ensured it matches.
        # We also accept paths that are already relative to root for flexibility.
        p = virtual_path
        # Normalize: remove leading /workspace prefix if present
        prefix = DEFAULT_WORKSPACE_PREFIX.rstrip("/")
        p = p.removeprefix(prefix)  # "/foo/bar" or "" or "/"
        # Now p is "/foo/bar" or "foo/bar" or "" — make it relative
        p = p.lstrip("/")
        candidate = (self.root_dir / p).resolve() if p else self.root_dir
        if self.virtual_mode and not candidate.is_relative_to(self.root_dir):
            raise ValueError(
                f"Path {virtual_path!r} escapes workspace root {str(self.root_dir)!r}"
            )
        return candidate

    # -- File operations ----------------------------------------------------

    def read_file(self, virtual_path: str) -> str:
        """Read a file at *virtual_path*.

        :param virtual_path: Virtual path.
        :return: File contents.
        """
        return self._resolve(virtual_path).read_text(encoding="utf-8")

    def write_file(self, virtual_path: str, content: str) -> None:
        """Write *content* to *virtual_path*, creating parents as needed.

        :param virtual_path: Virtual path.
        :param content: Text to write.
        """
        target = self._resolve(virtual_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def edit_file(self, virtual_path: str, old: str, new: str) -> None:
        """Replace *old* with *new* in the file at *virtual_path*.

        :param virtual_path: Virtual path.
        :param old: Text to replace.
        :param new: Replacement text.
        """
        target = self._resolve(virtual_path)
        text = target.read_text(encoding="utf-8")
        if old not in text:
            raise ValueError(f"Pattern {old!r} not found in {virtual_path!r}")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")

    def delete(self, virtual_path: str) -> None:
        """Delete file or directory at *virtual_path*.

        :param virtual_path: Virtual path.
        """
        target = self._resolve(virtual_path)
        if target.is_dir():
            import shutil

            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def ls(self, virtual_path: str) -> list[str]:
        """List directory at *virtual_path*.

        :param virtual_path: Virtual path to a directory.
        :return: Sorted entry names.
        """
        target = self._resolve(virtual_path)
        return (
            sorted(p.name for p in target.iterdir()) if target.is_dir() else []
        )

    def glob(
        self, pattern: str, virtual_path: str = DEFAULT_WORKSPACE_PREFIX
    ) -> list[str]:
        """Glob under *virtual_path*.

        :param pattern: Glob pattern, e.g. ``**/*.py``.
        :param virtual_path: Virtual directory to glob inside.
        :return: Matching virtual paths.
        """
        base = self._resolve(virtual_path)
        # Use pathlib glob
        return [
            f"{DEFAULT_WORKSPACE_PREFIX.rstrip('/')}/{p.relative_to(self.root_dir)}"
            for p in base.glob(pattern)
        ]

    def grep(
        self, pattern: str, virtual_path: str = DEFAULT_WORKSPACE_PREFIX
    ) -> list[str]:
        """Grep for *pattern* under *virtual_path*.

        :param pattern: Regex pattern.
        :param virtual_path: Virtual directory to search.
        :return: Lines/paths matching (simple substring match).
        """
        import re

        rx = re.compile(pattern)
        base = self._resolve(virtual_path)
        hits: list[str] = []
        for f in base.rglob("*"):
            if f.is_file():
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                except (OSError, UnicodeDecodeError):
                    # Skip unreadable / non-text files (binary, permission, etc.)
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        rel = f.relative_to(self.root_dir)
                        hits.append(f"{rel}:{lineno}:{line.strip()}")
        return hits


class StateBackend:
    """Ephemeral in-memory store for agent-internal artifacts.

    Holds ``/large_tool_results`` and ``/conversation_history`` without
    touching disk.
    """

    def __init__(self) -> None:
        """Initialize the in-memory state store."""
        self._store: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """Get *key* or *default*.

        :param key: Virtual path key.
        :param default: Fallback.
        :return: Stored value or default.
        """
        return self._store.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set *key* to *value*.

        :param key: Virtual path key.
        :param value: Value to store.
        """
        self._store[key] = value

    def delete(self, key: str) -> None:
        """Delete *key* if present.

        :param key: Virtual path key.
        """
        self._store.pop(key, None)

    def list_keys(self, prefix: str = "") -> list[str]:
        """List keys with *prefix*.

        :param prefix: Filter prefix.
        :return: Matching keys.
        """
        return [k for k in self._store if k.startswith(prefix)]


class VirtualBackend:
    """Routes virtual paths by prefix to the appropriate backend.

    :param state_backend: Backend for non-workspace paths.
    :param mapping: ``{prefix: filesystem_backend}`` mapping, e.g.
        ``{"/workspace/": FilesystemBackend(...)}``.
    """

    def __init__(
        self,
        state_backend: StateBackend,
        mapping: dict[str, FilesystemBackend],
    ) -> None:
        """Initialize the composite backend.

        :param state_backend: Default backend for non-workspace paths.
        :param mapping: ``{prefix: filesystem_backend}`` mapping.
        """
        self.state = state_backend
        # Normalize prefixes to end with "/"
        self.mapping: dict[str, FilesystemBackend] = {
            (k if k.endswith("/") else k + "/"): v for k, v in mapping.items()
        }

    def _route(self, virtual_path: str) -> tuple[str, Any]:
        """Route *virtual_path* to the correct backend.

        :param virtual_path: Virtual path.
        :return: (prefix, backend) or ("", state_backend) for non-workspace.
        """
        for prefix, backend in self.mapping.items():
            if virtual_path == prefix.rstrip("/") or virtual_path.startswith(
                prefix
            ):
                return prefix, backend
        return "", self.state

    def resolve(self, virtual_path: str) -> Path | Any:
        """Resolve *virtual_path* via the appropriate backend.

        :param virtual_path: Virtual path.
        :return: Real path (filesystem) or stored value (state).
        """
        _prefix, backend = self._route(virtual_path)
        if isinstance(backend, FilesystemBackend):
            return backend._resolve(virtual_path)
        return backend.get(virtual_path)


def make_backend(
    root_dir: str | Path,
    *,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
    virtual_mode: bool = True,
) -> VirtualBackend:
    """Build a composite backend rooted at *root_dir*.

    :param root_dir: Real working directory.
    :param workspace_prefix: Virtual mount point (must start and end with ``/``).
    :param virtual_mode: Sandbox escapes (recommended True).
    :return: Configured backend.
    """
    fs_backend = FilesystemBackend(
        root_dir=str(Path(root_dir).expanduser().resolve()),
        virtual_mode=virtual_mode,
    )
    return VirtualBackend(StateBackend(), {workspace_prefix: fs_backend})


def resolve_workspace_paths(
    paths: list[str] | list[str | tuple[str, str]],
    root_dir: str | Path,
    workspace_prefix: str = DEFAULT_WORKSPACE_PREFIX,
) -> list[str | tuple[str, str]]:
    """Translate on-disk skill/memory paths to workspace-virtual paths.

    :param paths: Skill/memory sources: bare paths or ``(path, label)`` tuples.
    :param root_dir: Real working directory.
    :param workspace_prefix: Virtual mount point.
    :return: Sources with path half translated to virtual form.
    :raises ValueError: If a path is outside the workspace.
    """
    root = Path(root_dir).expanduser().resolve()
    prefix = workspace_prefix.rstrip("/")

    def _translate(path: str) -> str:
        p = Path(path).expanduser()
        if p.is_absolute() and p.is_relative_to(Path(prefix)):
            return path
        if p.is_absolute():
            resolved = p.resolve()
            if resolved.is_relative_to(root):
                return f"{prefix}/{resolved.relative_to(root)}"
            raise ValueError(
                f"Path {path!r} is outside the workspace root {root!r}; "
                "skills/memory must live under the mounted workspace"
            )
        resolved = (root / p).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(
                f"Relative path {path!r} escapes the workspace root {root!r}"
            )
        return f"{prefix}/{resolved.relative_to(root)}"

    translated: list[str | tuple[str, str]] = []
    for entry in paths:  # type: ignore[assignment]
        if isinstance(entry, tuple):
            path, label = entry  # type: ignore[misc]
            translated.append((_translate(path), label))
        else:
            translated.append(_translate(entry))  # type: ignore[arg-type]
    return translated
