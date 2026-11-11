"""Mid-run steering that survives the process — phase 1c, slice c.

On ``LiveRun`` a steer is ``AgentRun.enqueue``, which only exists while a run is
live: it is a method on the run context, so it cannot outlive the run and cannot
be called from outside it. The durable host needs steering that survives a
restart, and the SDK's own semantics say what that is — ``enqueue``'s
``priority`` documentation: *"at a deferred-tool pause the content is added to
the history instead"*. Between passes, a steer **is** history.

So this module is a small durable store, keyed by run id: the steer endpoint
writes to it, and the next pass reads it and carries the text into the run as a
user turn. That keeps one rule for both cases — a steer either joins the run
in flight (the endpoint appends it) or waits for the next pass (the store) — and
neither needs a process to stay alive to hold it.

The store is a JSON file beside the queue, written atomically, for the same
reason the queue is SQLite: berg owns it, and it is readable by any process.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


def _store_dir() -> Path:
    """Where steers wait, under berg's own config dir."""
    from berg_agents.config.paths import resolve_config_dir

    return resolve_config_dir(None) / "workflow-steers"


def _path_for(run_id: str) -> Path:
    """One run's steer file."""
    return _store_dir() / f"{run_id}.json"


def append_steer(run_id: str, text: str) -> None:
    """Record one steer for a run.

    Appending rather than replacing, because a user may send two messages while
    a run is paused and both must reach the model.

    :param run_id: The run the text is addressed to.
    :param text: The user's message.
    """
    if not text.strip():
        return
    path = _path_for(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_steers(run_id)
    existing.append(text)
    # Atomic replace: a crash mid-write must never leave a half-written file
    # that the next pass reads as garbage.
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(existing, file)
        Path(tmp).replace(path)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()


def read_steers(run_id: str) -> list[str]:
    """The steers waiting for a run, oldest first."""
    path = _path_for(run_id)
    if not path.is_file():
        return []
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str) and item.strip()]


def clear_steers(run_id: str) -> None:
    """Drop a run's steers once a pass has carried them.

    :param run_id: The run whose steers were consumed.
    """
    path = _path_for(run_id)
    if path.is_file():
        path.unlink(missing_ok=True)
