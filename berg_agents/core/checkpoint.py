"""BergAgents checkpoint store for the framework-free agentic loop.

This module provides the *pluggable* persistence layer that
:class:`berg_agents.core.loop.BergLoop` uses to survive a process crash
or a human-in-the-loop pause.

Design goals
------------
1. **Framework agnostic.** The BergAgents runtime
   must not silently pull in framework code.  The grep gate in
   ``tests/test_core_checkpoint.py`` enforces this.
2. **Pure data on disk.** A snapshot is a JSON-serializable ``dict`` —
   no Python objects, no class references, no class-bound methods.  The
   loop is responsible for producing it (it can copy any tool
   ``ToolSpec`` by serializing its ``params``); the checkpoint store
   just stores and returns it.
3. **Multiple backends.** :class:`InMemoryCheckpointer` is the default
   (process-local, non-durable).  :class:`FileCheckpointer` writes one
   ``.json`` file per thread under a directory, so the same resume can
   run from a different process.  Both implement the
   :class:`Checkpointer` protocol.
4. **Thread-safe.** Multiple threads may call ``put`` / ``get`` on the
   same backend at once.  The in-memory backend uses a
   :class:`threading.RLock`; the file backend uses a per-thread
   :class:`threading.Lock` map to serialize the disk write.
5. **Generator-friendly.** ``list()`` yields thread ids in lexicographic
   order; ``get()`` returns ``None`` when the thread has no snapshot.


"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
import copy
import json
from pathlib import Path
import re
import threading
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Public protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Checkpointer(Protocol):
    """Pluggable persistence for one thread's state.

    Implementations MUST be safe to call from multiple threads.  The
    snapshot is opaque to the store — it is whatever the loop decided
    to write.  Implementations MUST round-trip every value the loop is
    likely to write (str, int, float, bool, None, list, dict, nested
    combos of the above).
    """

    def put(self, thread_id: str, snapshot: Mapping[str, Any]) -> None:
        """Replace any existing snapshot for *thread_id* with *snapshot*.

        :param thread_id: Stable thread identifier (e.g. UUID, or the
            OpenAI/Anthropic ``thread_id``).
        :param snapshot: JSON-serializable state to persist.
        :raises ValueError: If *snapshot* is not a mapping.
        """
        ...

    def get(self, thread_id: str) -> dict[str, Any] | None:
        """Return the snapshot for *thread_id* or ``None`` if absent.

        :param thread_id: Thread identifier to look up.
        :return: A *copy* of the stored snapshot (so the caller may
            mutate it without affecting the store), or ``None``.
        """
        ...

    def list(self) -> list[str]:
        """Return all known thread ids in lexicographic order."""
        ...

    def delete(self, thread_id: str) -> bool:
        """Remove the snapshot for *thread_id*.

        :param thread_id: Thread identifier to drop.
        :return: ``True`` if a snapshot was removed, ``False`` if no
            snapshot existed.
        """
        ...


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


class InMemoryCheckpointer:
    """Process-local :class:`Checkpointer` (default backend).

    Snapshots live in a ``dict`` protected by a re-entrant lock so the
    same thread may safely call ``put`` then ``get`` without deadlocking.
    Useful for tests, short-lived CLI runs, and the default
    ``build_berg_agents`` configuration.  Not durable across process
    restarts — see :class:`FileCheckpointer` for that.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def put(self, thread_id: str, snapshot: Mapping[str, Any]) -> None:
        """Replace the snapshot for *thread_id* with a deep copy of *snapshot*.

        The store keeps a deep copy so the caller can safely mutate the
        original mapping (or any of its nested lists / dicts) after
        ``put`` returns without affecting what the store hands back to
        a later ``get``.

        :param thread_id: Stable thread identifier.
        :param snapshot: JSON-serializable state.
        :raises TypeError: If *snapshot* is not a :class:`Mapping`.
        """
        if not isinstance(snapshot, Mapping):
            raise TypeError(
                f"snapshot must be a mapping; got {type(snapshot).__name__}"
            )
        with self._lock:
            # ``dict(snapshot)`` first: guarantees the top level is a dict
            # (the stored type is ``dict[str, Any]``), then deep-copy so the
            # nested lists / dicts are not shared with the caller.
            self._snapshots[thread_id] = copy.deepcopy(dict(snapshot))

    def get(self, thread_id: str) -> dict[str, Any] | None:
        """Return a deep copy of the snapshot for *thread_id* or ``None``.

        The returned dict (and its nested lists / dicts) is independent
        of the store, so the caller may mutate it freely without
        corrupting what a later ``get`` returns for the same thread.

        :param thread_id: Thread identifier to look up.
        :return: Deep copy of the stored snapshot, or ``None``.
        """
        with self._lock:
            snap = self._snapshots.get(thread_id)
        return None if snap is None else copy.deepcopy(snap)

    def list(self) -> list[str]:
        """Return all known thread ids sorted lexicographically.

        :return: Sorted list of thread ids.
        """
        with self._lock:
            return sorted(self._snapshots.keys())

    def delete(self, thread_id: str) -> bool:
        """Remove the snapshot for *thread_id*.

        :param thread_id: Thread identifier to drop.
        :return: ``True`` if a snapshot was removed, ``False`` otherwise.
        """
        with self._lock:
            return self._snapshots.pop(thread_id, None) is not None

    def __len__(self) -> int:
        """Return the number of stored snapshots (mostly for tests)."""
        with self._lock:
            return len(self._snapshots)


# ---------------------------------------------------------------------------
# File-based backend
# ---------------------------------------------------------------------------


class FileCheckpointer:
    """Filesystem-backed :class:`Checkpointer`.

    One ``<thread_id>.json`` file per thread, written atomically via a
    ``<thread_id>.json.tmp`` rename.  The :class:`threading.Lock` is
    held only for the duration of the rename so concurrent threads do
    not observe a half-written file.

    Use this when the same loop should resume across process boundaries
    (the FastAPI web UI, a long-lived orchestration job, a remote MCP
    server that calls ``loop.resume`` from a different Python process).
    """

    #: File name template; ``{thread_id}`` is replaced with the
    #: sanitized thread id (any non-identifier character becomes ``_``).
    _FILENAME = "{thread_id}.json"
    _TMP_SUFFIX = ".tmp"

    def __init__(self, directory: str | Path) -> None:
        """Create the on-disk directory if needed and prepare the backend.

        :param directory: Directory to store ``<thread_id>.json`` files.
            Created if it does not exist.
        """
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        # per-thread locks so different threads do not block each other
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # -- helpers ----------------------------------------------------------

    def _path_for(self, thread_id: str) -> Path:
        """Return the on-disk path for *thread_id* (no I/O).

        :param thread_id: Thread identifier.
        :return: Absolute :class:`Path` to the snapshot file.
        """
        safe = _sanitise_thread_id(thread_id)
        return self._dir / self._FILENAME.format(thread_id=safe)

    def _lock_for(self, thread_id: str) -> threading.Lock:
        """Return the per-thread lock, creating it lazily.

        :param thread_id: Thread identifier.
        :return: The :class:`threading.Lock` guarding this thread's file.
        """
        with self._locks_guard:
            lock = self._locks.get(thread_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[thread_id] = lock
            return lock

    # -- Checkpointer API -------------------------------------------------

    def put(self, thread_id: str, snapshot: Mapping[str, Any]) -> None:
        """Atomically write *snapshot* as ``<thread_id>.json``.

        The write goes through a ``.tmp`` file so a crash mid-write
        never leaves a half-written snapshot.  On POSIX the rename is
        atomic when source and destination are on the same filesystem.

        :param thread_id: Stable thread identifier.
        :param snapshot: JSON-serializable state.
        :raises TypeError: If *snapshot* is not a mapping.
        :raises ValueError: If *thread_id* cannot be safely converted to
            a filename.
        :raises OSError: If the write fails (disk full, permission, ...).
        """
        if not isinstance(snapshot, Mapping):
            raise TypeError(
                f"snapshot must be a mapping; got {type(snapshot).__name__}"
            )
        path = self._path_for(thread_id)
        tmp = path.with_suffix(path.suffix + self._TMP_SUFFIX)
        payload = json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True)
        with self._lock_for(thread_id):
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)

    def get(self, thread_id: str) -> dict[str, Any] | None:
        """Read the snapshot for *thread_id* or return ``None``.

        :param thread_id: Thread identifier.
        :return: A *new* dict parsed from the file, or ``None`` if the
            file is absent.
        :raises json.JSONDecodeError: If the file exists but is not
            valid JSON (treated as a corruption error, not as missing).
        """
        path = self._path_for(thread_id)
        if not path.exists():
            return None
        with self._lock_for(thread_id):
            text = path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        result = json.loads(text)
        if not isinstance(result, dict):
            # A snapshot MUST be an object; treat anything else as
            # corruption and surface it loudly rather than silently
            # return None (which would look like "no snapshot").
            raise TypeError(
                f"snapshot for {thread_id!r} is not a JSON object: "
                f"{type(result).__name__}"
            )
        return result

    def list(self) -> list[str]:
        """Return all known thread ids (filenames without the ``.json``).

        :return: Sorted list of thread ids.
        """
        ids: list[str] = []
        for child in self._dir.iterdir():
            if child.suffix == ".json" and child.is_file():
                ids.append(child.stem)
        return sorted(ids)

    def delete(self, thread_id: str) -> bool:
        """Remove the snapshot file for *thread_id*.

        :param thread_id: Thread identifier to drop.
        :return: ``True`` if a file was removed, ``False`` otherwise.
        """
        path = self._path_for(thread_id)
        with self._lock_for(thread_id):
            if path.exists():
                path.unlink()
                return True
            return False


# ---------------------------------------------------------------------------
# Snapshot shape helpers (the loop uses these to build what it stores)
# ---------------------------------------------------------------------------


def make_snapshot(
    *,
    thread_id: str,
    messages: Sequence[Mapping[str, Any]],
    step: int,
    tool_calls: int,
    pending_hitl: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a snapshot dict in the canonical shape the loop expects.

    Centralizing the shape here means the loop never has to know about
    field names, and the file backend round-trips the same dict that
    the in-memory backend stores.

    :param thread_id: Stable thread identifier.
    :param messages: OpenAI-shaped message list (the loop's running
        conversation state).  Declared as :class:`Sequence` rather than
        :class:`list` so callers can pass any iterable of mappings
        (``list[dict[str, str]]`` is *not* assignable to
        ``list[Mapping[str, Any]]`` because ``list`` is invariant).
    :param step: Index of the last completed step (0 == no steps yet).
    :param tool_calls: Total tool calls dispatched so far.
    :param pending_hitl: Optional :class:`HitlRequest` serialized to a
        dict (see :mod:`berg_agents.core.hitl`).  ``None`` when the
        loop is not paused.
    :param metadata: Optional caller-defined dict (model name, token
        counts, etc.).  ``None`` becomes an empty dict.
    :return: A JSON-serializable dict ready to pass to
        :meth:`Checkpointer.put`.
    """
    return {
        "thread_id": thread_id,
        "messages": [dict(m) for m in messages],
        "step": step,
        "tool_calls": tool_calls,
        "pending_hitl": (
            dict(pending_hitl) if pending_hitl is not None else None
        ),
        "metadata": dict(metadata) if metadata is not None else {},
        "schema_version": 1}


def iter_snapshots(
    checkpointer: Checkpointer,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(thread_id, snapshot)`` for every thread in *checkpointer*.

    Convenience for callers that need to walk every persisted state
    (e.g. an export job, a test that asserts on the whole store).

    :param checkpointer: The :class:`Checkpointer` to read.
    :return: Iterator of ``(thread_id, snapshot)`` pairs.
    """
    for thread_id in checkpointer.list():
        snap = checkpointer.get(thread_id)
        if snap is not None:
            yield thread_id, snap


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# Characters that survive sanitization verbatim; everything else becomes
# ``_`` (path separators are rejected outright, never replaced, so a
# traversal attempt can never silently turn into a valid filename).
_SAFE_THREAD_ID_CHAR = re.compile(r"[A-Za-z0-9._-]")


def _sanitise_thread_id(thread_id: str) -> str:
    """Return a filesystem-safe filename stem for *thread_id*.

    ``[A-Za-z0-9._-]`` passes through unchanged; any other character
    becomes ``_``.  Empty ids and ids containing path separators are
    rejected with :class:`ValueError` instead of being mangled, so a
    traversal attempt fails loudly at the boundary.

    :param thread_id: Stable thread identifier.
    :return: Sanitized filename stem (no extension, no directory).
    :raises ValueError: If *thread_id* is empty, contains a path
        separator, or sanitizes to ``.`` / ``..``.
    """
    if not thread_id:
        raise ValueError("thread_id must be a non-empty string")
    if "/" in thread_id or "\\" in thread_id or "\x00" in thread_id:
        raise ValueError(
            f"thread_id {thread_id!r} is not filesystem-safe: "
            "path separators are forbidden"
        )
    safe = "".join(
        char if _SAFE_THREAD_ID_CHAR.fullmatch(char) else "_"
        for char in thread_id
    )
    if safe in {".", ".."}:
        raise ValueError(
            f"thread_id {thread_id!r} is not filesystem-safe: "
            "result would be a directory entry"
        )
    return safe


__all__ = [
    "Checkpointer",
    "FileCheckpointer",
    "InMemoryCheckpointer",
    "iter_snapshots",
    "make_snapshot"]
