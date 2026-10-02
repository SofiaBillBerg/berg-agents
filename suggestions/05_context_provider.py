"""ContextProvider protocol — pluggable persistence for SessionContext.

The problem: today persistence is hard-wired. The loop has ``_persist_snapshot``
/ ``_load_snapshot`` that talk to a single ``Checkpointer`` interface (in-memory
or file), and the session state lives in a hand-rolled JSON shape. There's no
way to swap in Redis, SQLite, or a cloud store without touching the loop.

This module introduces a small protocol that owns persistence for the canonical
context:

    ``ContextProvider.load(thread_id) -> SessionContext | None``
    ``ContextProvider.save(thread_id, ctx) -> None``
    ``ContextProvider.delete(thread_id) -> bool``
    ``ContextProvider.list_ids() -> list[str]``

plus two implementations:

- ``InMemoryProvider`` — process-local, for tests and single-shot CLI runs.
- ``FileProvider`` — one ``.json`` per thread; designed to *evolve* the existing
  file-based checkpointer, not break it.

Back-compat bridge
------------------
``FileProvider`` has an ``legacy_bridge`` mode. When enabled it reads/writes the
**old** ``core.checkpoint`` JSON format and translates to/from
``SessionContext`` in both directions. That means:

- The existing web UI / TUI resume path keeps working unchanged.
- New code can call ``ContextProvider.save(thread_id, new_ctx)`` and get a typed
  object.

Both live in this file; no ``berg_agents/`` source is touched. The provider is
intended for use with a middleware (``06_context_middleware.py``) or a thin
adapter on top of the existing ``BergLoop`` / ``Harness``.

async/ sync
-----------
The protocol is async (matches the async-first runtime) but sync implementations
are allowed; a small ``sync_from`` helper converts sync ``load``/``save`` into
async.
"""

from __future__ import annotations

import abc
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


try:
    from context_deps import SessionContext, legacy_snapshot_from_session, load_with_migration
except ImportError:
    SessionContext = None  # type: ignore[assignment]
    legacy_snapshot_from_session = None
    load_with_migration = None


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ContextProvider(Protocol):
    """Pluggable persistence for a BergAgents session context.

    Methods:
        load(thread_id): Load the context for *thread_id* or ``None``.
        save(thread_id, ctx): Persist *ctx* for *thread_id*.
        delete(thread_id): Remove the context; ``True`` if it existed.
        list_ids(): List all known thread ids.
    """

    async def load(self, thread_id: str) -> SessionContext | None:
        ...

    async def save(self, thread_id: str, ctx: SessionContext) -> None:
        ...

    async def delete(self, thread_id: str) -> bool:
        ...

    async def list_ids(self) -> list[str]:
        ...


# ---------------------------------------------------------------------------
# In-memory provider
# ---------------------------------------------------------------------------

class InMemoryProvider(ContextProvider):
    """Process-local ``ContextProvider``.

    Snapshots live in a dict protected by a re-entrant lock. Useful for tests,
    single-shot CLI runs, and as a drop-in during migration. Not durable across
    process restarts.

    :ivar store: Internal mapping of thread_id -> SessionContext.
    """

    def __init__(self) -> None:
        """Create an empty in-memory store."""
        self._store: dict[str, SessionContext] = {}
        self._lock: asyncio.Lock | None = None

    async def _guard(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def load(self, thread_id: str) -> SessionContext | None:
        """Return a copy of the stored context or ``None``."""
        async with await self._guard():
            snap = self._store.get(thread_id)
            return None if snap is None else self._copy(snap)

    async def save(self, thread_id: str, ctx: SessionContext) -> None:
        """Replace any existing context for *thread_id* with a copy."""
        async with await self._guard():
            self._store[thread_id] = self._copy(ctx)

    async def delete(self, thread_id: str) -> bool:
        """Remove the context for *thread_id*; ``True`` if it existed."""
        async with await self._guard():
            return self._store.pop(thread_id, None) is not None

    async def list_ids(self) -> list[str]:
        """Return all thread ids, sorted."""
        async with await self._guard():
            return sorted(self._store.keys())

    @staticmethod
    def _copy(ctx: SessionContext) -> SessionContext:
        # Deep-ish copy for the mutable fields.
        new = dict(ctx.__dict__)
        new["messages"] = tuple(dict(m) for m in ctx.messages)
        new["usage"] = dict(ctx.usage)
        new["session_vars"] = dict(ctx.session_vars)
        new["metadata"] = dict(ctx.metadata)
        new["pending_hitl"] = (
            dict(ctx.pending_hitl) if ctx.pending_hitl is not None else None
        )
        return type(ctx)(**new)


# ---------------------------------------------------------------------------
# File provider
# ---------------------------------------------------------------------------

class FileProvider(ContextProvider):
    """Filesystem-backed ``ContextProvider``.

    One ``<thread_id>.json`` file per thread. Writes go through a ``.tmp``
    rename so a crash mid-write never leaves a half-written context.

    When ``legacy_bridge`` is set, the file is read/written in the **old**
    ``core.checkpoint.make_snapshot`` JSON format and translated to/from
    ``SessionContext`` on both sides. This lets the existing resume path keep
    working while new code consumes typed contexts.

    :param directory: Directory for the context files; created if missing.
    :param legacy_bridge: If ``True``, read/write the legacy checkpoint format.
    """

    def __init__(self, directory: str | Path, *, legacy_bridge: bool = False) -> None:
        """Create the directory if needed."""
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._legacy_bridge = legacy_bridge
        self._lock: dict[str, asyncio.Lock] = {}
        self._lock_guard: asyncio.Lock | None = None

    async def _lock_for(self, thread_id: str) -> asyncio.Lock:
        if self._lock_guard is None:
            self._lock_guard = asyncio.Lock()
        async with self._lock_guard:
            lock = self._lock.get(thread_id)
            if lock is None:
                lock = asyncio.Lock()
                self._lock[thread_id] = lock
            return lock

    def _path_for(self, thread_id: str) -> Path:
        safe = "".join(
            c if c.isidentifier() or c in "._" else "_"
            for c in thread_id
        )
        return self._dir / f"{safe}.json"

    # --- async API -------------------------------------------------------

    async def load(self, thread_id: str) -> SessionContext | None:
        """Read the context or ``None`` if absent.

        Raises ``ValueError`` if the file exists but is not valid JSON / a
        context (corruption detected).
        """
        path = self._path_for(thread_id)
        async with await self._lock_for(thread_id):
            if not path.exists():
                return None
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise OSError(f"cannot read {path}: {exc}") from exc
            if not text.strip():
                return None
            payload = json.loads(text)
            if self._legacy_bridge:
                return load_with_migration(payload)
            return self._load_ctx(payload)

    async def save(self, thread_id: str, ctx: SessionContext) -> None:
        """Atomically write *ctx* as ``<thread_id>.json``."""
        path = self._path_for(thread_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = self._serialize(ctx)
        async with await self._lock_for(thread_id):
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)

    async def delete(self, thread_id: str) -> bool:
        """Remove the context file; ``True`` if it existed."""
        path = self._path_for(thread_id)
        async with await self._lock_for(thread_id):
            if path.exists():
                path.unlink()
                return True
            return False

    async def list_ids(self) -> list[str]:
        """Return known thread ids (filenames without ``.json``), sorted."""
        ids: list[str] = []
        for child in self._dir.iterdir():
            if child.suffix == ".json" and child.is_file():
                ids.append(child.stem)
        return sorted(ids)

    # --- serialization ---------------------------------------------------

    def _serialize(self, ctx: SessionContext) -> str:
        if self._legacy_bridge and legacy_snapshot_from_session is not None:
            return json.dumps(
                legacy_snapshot_from_session(ctx),
                ensure_ascii=False,
                sort_keys=True,
            )
        return json.dumps(
            ctx.to_dict(), ensure_ascii=False, sort_keys=True
        )

    def _load_ctx(self, payload: dict[str, Any]) -> SessionContext:
        if SessionContext is None:
            raise RuntimeError("SessionContext not importable")
        return SessionContext.model_validate(payload)


# ---------------------------------------------------------------------------
# Back-compat bridge: ContextProvider built on top of the existing Checkpointer
# ---------------------------------------------------------------------------

try:
    from core.checkpoint import Checkpointer, make_snapshot

    def checkpointer_to_provider(
        checkpointer: Checkpointer, *,
        description: str = "",
        task_type: str = "generic",
    ) -> ContextProvider:
        """Wrap the existing ``Checkpointer`` as a ``ContextProvider``.

        Reads the legacy snapshot, builds a ``SessionContext``, and writes back
        in the legacy format (so the loop's existing resume logic is unaffected).
        The extra fields carried in ``SessionContext`` (usage, session_vars,
        model_id) are persisted in ``metadata`` during the write so nothing is
        silently dropped.

        :param checkpointer: An existing checkpointer (``InMemoryCheckpointer``
            or ``FileCheckpointer``).
        :param description: Default task description when the snapshot lacks one.
        :param task_type: Default task type.
        :return: A ``ContextProvider`` wrapping the checkpointer.
        """

        async def _load(thread_id: str) -> SessionContext | None:
            snap = checkpointer.get(thread_id)
            if snap is None:
                return None
            try:
                ctx = SessionContext.from_snapshot(snap, version=1)
            except Exception:
                return None
            # Preserve any usage/session_vars the old shape never stored
            # by folding extras into metadata.
            extra_keys = {"usage", "session_vars", "model_id",
                          "complexity", "risk_level", "task_id", "created_at",
                          "updated_at"}
            snap_meta = snap.get("metadata", {})
            snap_meta = dict(snap_meta)
            for k in extra_keys - {"metadata"}:
                if k in snap:
                    snap_meta[k] = snap[k]
            snap_meta["metadata"] = snap_meta
            ctx = ctx.model_copy(update={"metadata": snap_meta})
            return ctx

        async def _save(thread_id: str, ctx: SessionContext) -> None:
            meta = dict(ctx.metadata)
            for k in {"usage", "session_vars", "model_id", "task_id"}:
                if getattr(ctx, k, None) not in (None, {}):
                    meta[k] = getattr(ctx, k)
            legacy = make_snapshot(
                thread_id=thread_id,
                messages=list(ctx.messages),
                step=ctx.step,
                tool_calls=ctx.tool_calls,
                pending_hitl=(dict(ctx.pending_hitl) if ctx.pending_hitl else None),
                metadata=meta or None,
            )
            checkpointer.put(thread_id, legacy)

        async def _delete(thread_id: str) -> bool:
            return checkpointer.delete(thread_id)

        async def _list_ids() -> list[str]:
            return checkpointer.list()

        class _BridgeProvider(ContextProvider):
            load = _load
            save = _save
            delete = _delete
            list_ids = _list_ids

        return _BridgeProvider()

except ImportError:
    def checkpointer_to_provider(*_args: Any, **_kwargs: Any) -> ContextProvider:  # type: ignore[assignment,misc]
        """Unavailable without the checkpointer.

        Returns a no-op provider that raises on every call.
        """
        class _NoopProvider(ContextProvider):
            async def load(self, *_: Any, **__: Any) -> None:
                return None
            async def save(self, *_: Any, **__: Any) -> None:
                raise RuntimeError("checkpointer not available")
            async def delete(self, *_: Any, **__: Any) -> bool:
                return False
            async def list_ids(self, *_: Any, **__: Any) -> list[str]:
                return []

        return _NoopProvider()


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------

def sync_from(provider: ContextProvider) -> "SyncContextProvider":
    """Adapt an async ``ContextProvider`` to a synchronous one."""
    return SyncContextProvider(provider)


class SyncContextProvider:
    """Sync view over an async ``ContextProvider``."""

    def __init__(self, provider: ContextProvider) -> None:
        self._provider = provider

    def load(self, thread_id: str) -> SessionContext | None:
        return asyncio.run(self._provider.load(thread_id))

    def save(self, thread_id: str, ctx: SessionContext) -> None:
        asyncio.run(self._provider.save(thread_id, ctx))

    def delete(self, thread_id: str) -> bool:
        return asyncio.run(self._provider.delete(thread_id))

    def list_ids(self) -> list[str]:
        return asyncio.run(self._provider.list_ids())
