"""SessionContext — the canonical, typed model for a berg_agents thread/session.

This is the single source of truth that unifies four previously fragmented
shapes:

  1. ``core.interface.TaskContext`` / ``AgentResult`` — the agent contract.
  2. ``harness/orchestrator.py`` — a hand-built plain ``dict``.
  3. ``core.checkpoint.make_snapshot`` — an implicit JSON shape with
     ``messages`` / ``step`` / ``tool_calls`` / ``pending_hitl`` / ``metadata``.
  4. ``pydantic_ai.RunContext`` — the live run object (messages, usage, model).

SessionContext also fills the gaps the old snapshot had: there is **no** place
for LLM usage / token counts / model id / session variables anywhere in the
current checkpoint layer, so that state was invisible to persistence and the UI.

Design decisions
----------------
- Frozen dataclass for immutability; ``model_dump()`` / ``model_validate()``
  for JSON round-trips (schema generation, API serialization).
- ``schema_version: int`` with ``from_snapshot()`` migration so a future schema
  bump can be handled at load time instead of everywhere.
- ``SessionContext`` is the *input* schema for the provider; ``to_snapshot()``
  produces a backward-compatible legacy snapshot (still accepted by the current
  ``core.checkpoint.make_snapshot`` shape) so the existing web UI / TUI resuming
  path keeps working.

This file is standalone — it imports only stdlib + pydantic. No berg_agents
source is modified.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Canonical model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionContext:
    """Immutable snapshot of a single BergAgents thread/session.

    All fields are typed so the layer can validate at load time, generate
    OpenAPI/JSON schemas for the web UI, and emit meaningful tracing logs.

    Attributes:
        schema_version: Schema major version; used for migration.
        thread_id: Stable thread identifier (the thing the checkpointer keyed on).
        task_id: The task/task-run id (often == thread_id).
        description: Human-readable task description.
        task_type: Machine task type (e.g. ``edit_file``, ``generic``, ``plan``).
        complexity: ``trivial | standard | complex | critical``.
        risk_level: ``low | medium | high | critical``.
        model_id: Model the run used; ``None`` for tool-only / offline runs.
        messages: Full conversation so far (OpenAI-shaped).
        step: Index of the last completed loop step.
        tool_calls: Total tool calls dispatched so far.
        usage: LLM usage record (per-model token counts, cost).
        session_vars: Per-session mutable state the agents agree to use (keyed by name).
        pending_hitl: A serialized ``HitlRequest`` when the loop is paused; ``None`` otherwise.
        metadata: Arbitrary caller-defined extra data (kept but *not* the canonical
            place for runtime state — use ``session_vars`` instead).
        created_at: ISO timestamp when the session was first created.
        updated_at: ISO timestamp of the last persisted update.
    """

    schema_version: int = 1
    thread_id: str
    task_id: str
    description: str
    task_type: str
    complexity: str = "standard"
    risk_level: str = "low"
    model_id: str | None = None
    messages: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    step: int = 0
    tool_calls: int = 0
    usage: dict[str, Any] = field(default_factory=dict)
    session_vars: dict[str, Any] = field(default_factory=dict)
    pending_hitl: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: _now_iso())
    updated_at: str = field(default_factory=lambda: _now_iso())

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def new(cls, thread_id: str, description: str, task_type: str = "generic",
            complexity: str = "standard", risk_level: str = "low") -> SessionContext:
        """Create a fresh session for a new task.

        :param thread_id: Stable thread identifier.
        :param description: Human-readable task description.
        :param task_type: Machine task type.
        :param complexity: Complexity level.
        :param risk_level: Risk level.
        :return: New frozen session context.
        """
        return cls(
            thread_id=thread_id,
            task_id=thread_id,
            description=description,
            task_type=task_type,
            complexity=complexity,
            risk_level=risk_level,
            messages=(),
            step=0,
            tool_calls=0,
        )

    @classmethod
    def from_snapshot(cls, legacy_snapshot: dict[str, Any], *, version: int = 1) -> SessionContext:
        """Migrate a legacy ``core.checkpoint.make_snapshot``-style dict into the
        canonical model.

        The legacy shape:

        .. code-block:: python

            {
                "thread_id": "...",
                "messages": [...],
                "step": 0,
                "tool_calls": 0,
                "pending_hitl": {...} | None,
                "metadata": {...},
                "schema_version": 1}

        :param legacy_snapshot: A snapshot read from a legacy checkpoint file.
        :param version: Legacy schema version (currently always 1).
        :return: A ``SessionContext`` populated from the legacy shape.
        :raises ValueError: If the legacy snapshot is missing required keys.
        """
        if "thread_id" not in legacy_snapshot:
            raise ValueError("legacy snapshot missing 'thread_id'")
        if "messages" not in legacy_snapshot:
            raise ValueError("legacy snapshot missing 'messages'")
        return cls(
            schema_version=version,
            thread_id=legacy_snapshot["thread_id"],
            task_id=legacy_snapshot.get("thread_id", ""),
            description=legacy_snapshot.get("description", ""),
            task_type=legacy_snapshot.get("task_type", "generic"),
            complexity=legacy_snapshot.get("complexity", "standard"),
            risk_level=legacy_snapshot.get("risk_level", "low"),
            model_id=legacy_snapshot.get("model_id"),
            messages=tuple(dict(m) for m in legacy_snapshot["messages"]),
            step=int(legacy_snapshot.get("step", 0)),
            tool_calls=int(legacy_snapshot.get("tool_calls", 0)),
            usage=legacy_snapshot.get("usage", {}),
            session_vars=legacy_snapshot.get("session_vars", {}),
            pending_hitl=dict(legacy_snapshot["pending_hitl"])
            if legacy_snapshot.get("pending_hitl") else None,
            metadata=dict(legacy_snapshot.get("metadata", {})),
        )

    @classmethod
    def from_run_context(cls, context: Any, *,
                         thread_id: str,
                         description: str = "",
                         task_type: str = "generic") -> SessionContext:
        """Build a ``SessionContext`` from a live ``pydantic_ai.RunContext``.

        Pulls the live conversation, usage, model id, and run limits from the
        context so a middleware can persist exactly what the model just saw.

        :param context: A ``pydantic_ai.RunContext`` instance.
        :param thread_id: Thread identifier to key persistence on.
        :param description: Task description if not derivable from messages.
        :param task_type: Task type if not derivable from messages.
        :return: A ``SessionContext`` reflecting the run's current state.
        """
        messages = tuple(dict(m) for m in context.messages)
        usage: dict[str, Any] = {}
        if hasattr(context, "usage") and context.usage is not None:
            u = context.usage
            usage = {
                "request_tokens": getattr(u, "request_tokens", None),
                "completion_tokens": getattr(u, "completion_tokens", None),
                "total_tokens": getattr(u, "total_tokens", None)}
        model_id: str | None = None
        if hasattr(context, "_model_id") and context._model_id:
            model_id = str(context._model_id)
        elif hasattr(context, "model"):
            model_id = getattr(context.model, "model_name", None) or model_id
        return cls(
            thread_id=thread_id,
            task_id=thread_id,
            description=description or _extract_description_from_messages(messages),
            task_type=task_type,
            messages=messages,
            step=len(messages) // 2,  # rough approximation of completed steps
            tool_calls=sum(1 for m in messages if m.get("role") == "tool"),
            usage=usage,
            model_id=model_id,
        )

    # ------------------------------------------------------------------
    # Projections
    # ------------------------------------------------------------------

    def with_messages(self, *new_messages: dict[str, Any]) -> SessionContext:
        """Return a new context with messages appended.

        :param new_messages: Message dicts to append.
        :return: A new frozen ``SessionContext``.
        """
        return self.__class__(
            **self.__dict__,
            messages=self.messages + tuple(new_messages),
            updated_at=_now_iso(),
        )

    def with_hitl(self, pending_hitl: dict[str, Any]) -> SessionContext:
        """Return a new context with a pending HITL request.

        :param pending_hitl: Serialized HITL request dict.
        :return: A new frozen ``SessionContext``.
        """
        return self.__class__(
            **self.__dict__,
            pending_hitl=dict(pending_hitl),
            updated_at=_now_iso(),
        )

    def clear_hitl(self) -> SessionContext:
        """Return a new context with the HITL request cleared.

        :return: A new frozen ``SessionContext``.
        """
        return self.__class__(
            **self.__dict__,
            pending_hitl=None,
            updated_at=_now_iso(),
        )

    def with_step(self, step: int) -> SessionContext:
        """Return a new context advanced to *step*.

        :param step: New step index.
        :return: A new frozen ``SessionContext``.
        """
        return self.__class__(
            **self.__dict__,
            step=step,
            tool_calls=self.tool_calls,
            updated_at=_now_iso(),
        )

    def with_tool_call(self) -> SessionContext:
        """Return a new context with the tool-call counter incremented.

        :return: A new frozen ``SessionContext``.
        """
        return self.__class__(
            **self.__dict__,
            tool_calls=self.tool_calls + 1,
            updated_at=_now_iso(),
        )

    def session_var(self, name: str, default: Any = None) -> Any:
        """Read a session variable by name.

        :param name: Variable name.
        :param default: Fallback when the variable is absent.
        :return: The stored value or *default*.
        """
        return self.session_vars.get(name, default)

    def set_session_var(self, name: str, value: Any) -> SessionContext:
        """Return a new context with *name* set in ``session_vars``.

        :param name: Variable name.
        :param value: Value to store.
        :return: A new frozen ``SessionContext``.
        """
        new_vars = dict(self.session_vars)
        new_vars[name] = value
        return self.__class__(
            **self.__dict__,
            session_vars=new_vars,
            updated_at=_now_iso(),
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_snapshot(self) -> dict[str, Any]:
        """Emit the legacy-compatible snapshot shape.

        Produces a dict that looks like the output of
        ``core.checkpoint.make_snapshot`` so the existing read path can
        consume it unchanged.

        :return: Legacy-compatible snapshot dict.
        """
        return {
            "thread_id": self.thread_id,
            "task_id": self.task_id,
            "description": self.description,
            "task_type": self.task_type,
            "complexity": self.complexity,
            "risk_level": self.risk_level,
            "model_id": self.model_id,
            "messages": list(self.messages),
            "step": self.step,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
            "pending_hitl": self.pending_hitl,
            "session_vars": self.session_vars,
            "metadata": self.metadata,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at}

    def to_dict(self) -> dict[str, Any]:
        """Full canonical shape as a plain dict.

        :return: Plain dict representation.
        """
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# Legacy snapshot reader (back-compat bridge, opt-in)
# ---------------------------------------------------------------------------

def legacy_snapshot_from_session(ctx: SessionContext, step: int | None = None,
                                 pending_hitl: dict[str, Any] | None = None) -> dict[str, Any]:
    """Emit a snapshot in the exact shape ``core.checkpoint.make_snapshot`` produces.

    This is a back-compat helper: the legacy reader expects *only* the keys
    ``thread_id, messages, step, tool_calls, pending_hitl, metadata`` plus the
    optional ``schema_version``. Fields not present in this function's output
    are silently ignored by the old reader, while the old reader's extra keys are
    absorbed by ``SessionContext.from_snapshot``.

    :param ctx: The canonical session context.
    :param step: Step to record (defaults to ``ctx.step``).
    :param pending_hitl: Pending HITL request to record.
    :return: Legacy snapshot dict.
    """
    snap = ctx.to_snapshot()
    return {
        "thread_id": snap["thread_id"],
        "messages": list(snap["messages"]),
        "step": step if step is not None else snap["step"],
        "tool_calls": snap["tool_calls"],
        "pending_hitl": pending_hitl,
        "metadata": dict(snap.get("metadata", {})),
        "schema_version": 1}


# ---------------------------------------------------------------------------
# Legacy migration registry (future-proofing for schema_version > 1)
# ---------------------------------------------------------------------------

_MIGRATIONS: dict[int, callable] = {}


def register_migration(from_version: int) -> callable:
    """Decorator to register a migration function for a legacy version.

    The registered function receives a legacy snapshot dict and returns a
    ``SessionContext``. Registered at import time.

    :param from_version: The legacy schema version this function migrates *from*.
    :return: The decorated function.
    """
    def decorator(fn):
        _MIGRATIONS[from_version] = fn
        return fn
    return decorator


@register_migration(1)
def _migrate_v1(snapshot: dict[str, Any]) -> SessionContext:
    """Migrate legacy v1 snapshots (the only version shipped).

    :param snapshot: A v1 snapshot dict.
    :return: Populated ``SessionContext``.
    """
    return SessionContext.from_snapshot(snapshot, version=1)


def load_with_migration(snapshot: dict[str, Any]) -> SessionContext:
    """Load a snapshot, applying the registered migration for its version.

    Falls back to the v1 handler if the version is unknown. A future version
    bump adds a handler here; nothing else changes.

    :param snapshot: Snapshot dict to load.
    :return: Migrated ``SessionContext``.
    """
    version = int(snapshot.get("schema_version", 1))
    handler = _MIGRATIONS.get(version)
    if handler is None:
        # Unknown version -> try the closest known handler (v1) so recovery
        # degrades gracefully instead of failing.
        handler = _MIGRATIONS.get(1, lambda s: SessionContext.from_snapshot(s, version=version))
    return handler(snapshot)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _extract_description_from_messages(messages: tuple[dict[str, Any], ...]) -> str:
    """Best-effort description from the first user message.

    :param messages: OpenAI-shaped message list.
    :return: Description string or empty.
    """
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content[:500]
            if isinstance(content, list):
                parts = [c.get("text", "") for c in content if isinstance(c, dict)]
                return " ".join(parts)[:500]
    return ""
