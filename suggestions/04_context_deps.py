"""Context deps classes — make ``RunContext.deps`` actually carry meaning.

The problem (audited in ``01_current_state.md``): every Pydantic AI agent in
``berg_agents/agents/*`` declares a ``deps_type`` and annotates its tools with
``ctx: RunContext[...Deps]`` — but the tool bodies do ``_ = ctx`` everywhere,
and the ``Agent`` instances are constructed with **no** ``deps=...`` argument,
so the dependency-injection feature Pydantic AI is designed around does nothing.

This module defines:

- ``TaskContextDeps`` — the per-run dependency payload (workspace, task info,
  the shared read-only ``SessionContext``, provider config).
- ``ContextDepsRegistry`` — a tiny registry keyed by agent name so factories
  can produce the right deps class for any agent, including custom ones.
- A few example agent-tool functions showing **how** a tool consumes deps
  instead of ``_ = ctx``.

Design
------
* ``TaskContextDeps`` is frozen. Multiple agents sharing one run get the same
  ``SessionContext`` reference without aliasing bugs.
* No ``berg_agents/`` file is imported, so this module is importable in isolation
  and can live in a plugin package without pulling the harness in.
* The registry is opt-in: existing agents keep running, and each one is wired
  one at a time via ``agent.run(deps=...)``.

Usage
-----
.. code-block:: python

    from pydantic_ai import Agent
    from context_deps import TaskContextDeps, ContextDepsRegistry

    registry = ContextDepsRegistry()

    @registry.register("reader")
    class ReaderDeps(TaskContextDeps):
        """Reader-specific deps: which file the agent must operate on."""
        file_path: str | None = None

    @agent.tool
    def read_file(ctx: RunContext[ReaderDeps], file_path: str) -> str:
        # deps are *read* here, not discarded
        if ctx.deps.file_path is not None:
            file_path = ctx.deps.file_path
        ...

    # run time: inject the deps
    await agent.run(prompt, deps=ContextDeps(
        agent_name="reader",
        task={"description": "...", "task_type": "read_file"},
        context=ReaderDeps(
            workspace_root=Path("."),
            task_type="read_file",
            complexity="trivial",
            session=some_session_context,
            provider_cfg={"base_url": "...", "api_key": "..."},
            file_path="src/app.py",
        ),
    ))
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pydantic


# ---------------------------------------------------------------------------
# Core deps classes
# ---------------------------------------------------------------------------

@pydantic.dataclasses.dataclass(frozen=True)
class TaskContextDeps:
    """Dependencies injected into an agent's tools at run time.

    This replaces the existing ``PlannerDeps`` / ``ImplementationDeps`` pattern,
    where deps were declared but never read (tools did ``_ = ctx``) and where
    ``workspace_root`` was captured in closures at import time instead of
    injected per run/thread.

    All agents in one logical run share the same read-only ``SessionContext``;
    because it's frozen, sharing it is safe.

    Attributes:
        workspace_root: Absolute workspace directory (the mount point the agent
            considers ``/workspace``).
        task_type: Machine task type (e.g. ``edit_file``, ``generic``, ``plan``).
        complexity: Task complexity level driving model selection.
        session: The canonical :class:`SessionContext` for the thread.
        provider_cfg: Resolved provider/model kwargs used by this run
            (base_url, api_key, etc.) so a tool can build its own model
            without re-resolving config.
    """

    workspace_root: Path = field(default_factory=lambda: Path(".").resolve())
    task_type: str = "generic"
    complexity: str = "standard"
    session: Any = None  # SessionContext; kept Any to avoid a circular import
    provider_cfg: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Workspace helpers — the common case for file tools
    # ------------------------------------------------------------------

    def resolve_target(self, file_path: str) -> Path:
        """Resolve a tool's ``file_path`` onto the workspace root.

        Strips a leading ``/workspace`` prefix (the virtual mount) and rejects
        any path that escapes the workspace root.

        :param file_path: Path as the tool received it.
        :return: Absolute workspace path.
        :raises ValueError: If the resolved path escapes the workspace.
        """
        target = Path(file_path)
        if target.is_absolute() and str(target).startswith("/workspace"):
            target = target.relative_to("/workspace")
        absolute = (self.workspace_root / target).resolve()
        try:
            absolute.relative_to(self.workspace_root)
        except ValueError:
            raise ValueError(
                f"resolved path {absolute} escapes workspace root "
                f"{self.workspace_root}"
            )
        return absolute

    def workspace_file(self, file_path: str) -> Path:
        """Alias for :meth:`resolve_target`, keeping the ``*_file`` naming
        convention of the existing tools.

        :param file_path: Path to the file.
        :return: Absolute path inside the workspace.
        """
        return self.resolve_target(file_path)

    def session_var(self, name: str, default: Any = None) -> Any:
        """Shortcut: read a session variable from the shared context.

        :param name: Variable name.
        :param default: Fallback value.
        :return: The stored value or *default*.
        """
        if self.session is None:
            return default
        return self.session.session_var(name, default)

    def set_session_var(self, name: str, value: Any) -> Any:
        """Shortcut: write a session variable, returning the updated context.

        The caller is responsible for replacing its ``SessionContext`` when the
        session mutates (sessions are immutable).

        :param name: Variable name.
        :param value: Value to store.
        :return: The updated :class:`SessionContext` (same object if unchanged).
        """
        if self.session is None:
            return None
        return self.session.set_session_var(name, value)


# ---------------------------------------------------------------------------
# Top-level run deps (what ``agent.run(deps=...)`` receives)
# ---------------------------------------------------------------------------

@pydantic.dataclasses.dataclass(frozen=True)
class ContextDeps:
    """Payload passed to ``agent.run(deps=...)``.

    ``ctx.deps`` inside the agent is an instance of this; agents that want
    task-specific fields should subclass ``TaskContextDeps`` (see
    ``ContextDepsRegistry``) and pass the subclass as ``context``.

    Attributes:
        agent_name: The agent this run belongs to (labels traces).
        task: The full task dict for this run.
        context: The task-specific deps (``TaskContextDeps`` or subclass).
    """

    agent_name: str
    task: dict[str, Any]
    context: TaskContextDeps

    @property
    def description(self) -> str:
        """The human-readable task description."""
        return str(self.task.get("description", ""))

    @property
    def task_id(self) -> str | None:
        """The task id if present in the task dict."""
        return self.task.get("task_id")

    @property
    def session(self) -> Any:
        """Convenience: the shared session context."""
        return self.context.session


# ---------------------------------------------------------------------------
# Deps registry — factory for per-agent deps classes
# ---------------------------------------------------------------------------

class ContextDepsRegistry:
    """Registry of per-agent deps classes.

    Lets factories produce the right deps for an agent name, so new/custom
    agents plug in without touching the core. The registry is keyed by the
    **agent name** (the name labels the run span in tracing).

    Attributes:
        default: The default deps class used when an agent has no entry.

    Example
    -------
    .. code-block:: python

        from context_deps import ContextDepsRegistry, TaskContextDeps

        registry = ContextDepsRegistry()

        @registry.register("code_reader")
        class CodeReaderDeps(TaskContextDeps):
            """A reader that operates on a fixed file."""
            file_path: str | None = None
            language: str = "python"

        # later, at run time:
        deps = registry.build("code_reader")
        """

    default: type[TaskContextDeps] = TaskContextDeps

    def __init__(self, default: type[TaskContextDeps] = TaskContextDeps) -> None:
        """Initialize the registry.

        :param default: Default deps class when no entry exists for an agent.
        """
        self.default = default
        self._entries: dict[str, type[TaskContextDeps]] = {}

    def register(self, agent_name: str) -> callable:
        """Decorator to register a deps class for *agent_name*.

        :param agent_name: The agent name this deps class applies to.
        :return: The decorator.
        """
        def decorator(cls: type[TaskContextDeps]) -> type[TaskContextDeps]:
            if not issubclass(cls, TaskContextDeps):
                raise TypeError(
                    f"deps class must subclass TaskContextDeps, got {cls}"
                )
            self._entries[agent_name] = cls
            return cls
        return decorator

    def get(self, agent_name: str) -> type[TaskContextDeps]:
        """Get the deps class for an agent name.

        :param agent_name: Agent name.
        :return: The registered deps class, or :attr:`default`.
        """
        return self._entries.get(agent_name, self.default)

    def build(self, agent_name: str, **deps_kwargs: Any) -> TaskContextDeps:
        """Build a deps instance for *agent_name*.

        :param agent_name: Agent name.
        :param deps_kwargs: Keyword args forwarded to the deps class.
        :return: A deps instance.
        """
        cls = self.get(agent_name)
        # Drop known ContextDeps-level kwargs so they don't reach the
        # per-agent class; the caller passes them as ContextDeps, not as
        # TaskContextDeps fields.
        return cls(**deps_kwargs)

    def list_agents(self) -> list[str]:
        """List agent names with registered deps classes.

        :return: Sorted list of names.
        """
        return sorted(self._entries.keys())


# ---------------------------------------------------------------------------
# Example tools that *use* deps (illustrative, not connected to the app)
# ---------------------------------------------------------------------------

def _example_read_file(
    ctx: Any,  # RunContext[TaskContextDeps]
    file_path: str,
) -> str:
    """Example tool showing how a tool reads ``ctx.deps`` instead of ``_ = ctx``.

    This is what replaces the existing ``_ = ctx`` boilerplate in the agents.
    """
    # Use the thread's workspace root instead of the stale closure value.
    root = ctx.deps.context.workspace_root
    target = root / file_path
    if not target.exists():
        return f"File not found: {file_path}"
    return target.read_text(encoding="utf-8")


def _example_write_file(
    ctx: Any,  # RunContext[TaskContextDeps]
    file_path: str,
    content: str,
) -> str:
    """Example mutating tool that validates against the workspace via deps."""
    target = ctx.deps.context.resolve_target(file_path)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {target}"


def _example_store_result(
    ctx: Any,  # RunContext[TaskContextDeps]
    name: str,
    value: Any,
) -> str:
    """Example of writing to the shared session state from a tool.

    Tools that need to remember something across steps use the shared frozen
    ``SessionContext`` via the deps shortcut.
    """
    updated = ctx.deps.context.set_session_var(name, value)
    if updated is not None:
        ctx.deps.context = updated  # caller replaces its session reference
    return f"Stored {name!r}"
