# Berg Agents is a sophisticated multi-agent system built with modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Live context-window usage, so a gauge can show what compaction sees.

``ReportContextUsage`` (a harness capability on the chat agent) emits a
``ContextUsageEvent`` on every model request. Nothing consumed it, so the
user had no way to see the context filling up or compaction approaching —
it just happened, mid-conversation, with the history suddenly shorter.

This module holds the most recent reading per session in memory and
serves it over REST. In-memory is deliberate: usage is a live gauge, not
a record; a restart starting from an unknown gauge is honest, whereas a
persisted stale "73%" would be a lie.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

#: Latest reading per session id. Guarded by _LOCK: the agent may report
#: from a worker thread while an HTTP handler reads it.
_lock = threading.Lock()
_latest: dict[str, dict[str, Any]] = {}


def record(session_id: str | None, event: Any) -> None:
    """Store a context-usage reading for a session.

    Reported values are **per request**, not cumulative: a fresh run's
    first requests have no usage anchor, so they report only the new
    suffix and the number can fall mid-session. Since the question the
    gauge answers is "how close am I to the limit?", the high-water mark
    is kept and shown; a per-request reading would under-report and
    mislead. Compaction is a separate event, so a mark that stays flat
    still reflects reality.

    Failure-isolated: a gauge must never break a chat turn.

    :param session_id: Session the run belongs to (None is ignored —
        there is nothing to attribute the reading to).
    :param event: ``ContextUsageEvent`` (used/window/fraction/resolved).
    """
    if not session_id:
        return
    try:
        reading = {
            "used_tokens": int(getattr(event, "used_tokens", 0) or 0),
            "window_tokens": int(getattr(event, "window_tokens", 0) or 0),
            "fraction": float(getattr(event, "fraction", 0.0) or 0.0),
            # False when the window is the harness fallback rather than
            # the model's real one, so the gauge can say it is a guess.
            "resolved": bool(getattr(event, "resolved", False))}
    except Exception as exc:
        logger.debug("context usage reading skipped: %s", exc)
        return
    with _lock:
        previous = _latest.get(session_id)
        # Keep the larger "used" reading as the high-water mark.
        _latest[session_id] = (
            reading
            if previous is None
            or reading["used_tokens"] >= previous["used_tokens"]
            else previous
        )


def latest(session_id: str | None) -> dict[str, Any] | None:
    """The latest reading for a session, or None when none was reported.

    :param session_id: Session identifier.
    :return: Reading dict, or None.
    """
    if not session_id:
        return None
    with _lock:
        return dict(_latest[session_id]) if session_id in _latest else None


def forget(session_id: str | None) -> None:
    """Drop a session's reading (called when the session is deleted)."""
    if not session_id:
        return
    with _lock:
        _latest.pop(session_id, None)
