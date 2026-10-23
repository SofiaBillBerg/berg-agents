# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
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

"""Server-side chat sessions (any browser, any directory).

Local-storage sessions are per-browser-profile: Chrome never sees what
OpenChamber's browser saved. This module persists the authoritative copy
server-side in SQLite (one database per project root), following the
Pydantic pattern of storing the framework side and converting at the
edge: ``ModelMessages`` in, ``dump_messages`` UI JSON out.

Session identity is a stable id (client thread id or minted uuid):
titles default to ``<project> #<seq> · <date>`` with the first user
message as subtitle, and renames are explicit user titles.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import logging
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

try:
    from pydantic_ai_harness.step_persistence.conversations import (
        ConversationSummary,
        SqliteConversationStore,
    )
except ImportError:  # pragma: no cover - harness optional at import time
    ConversationSummary = None  # type: ignore[assignment,misc]
    SqliteConversationStore = None  # type: ignore[assignment,misc]

#: Client-minted ids must stay narrow (they become filenames/keys).
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:-]{0,63}")

_stores: dict[str, Any] = {}


def _config_dir(root_dir: str | Path) -> Path:
    """Resolved config dir for a project (shared rule, see paths.py).

    Precedence: ``BERG_AGENTS_CONFIG_DIR``, project ``.berg-agents/``,
    then the global ``~/.berg-agents/``.
    """
    from berg_agents.config.paths import resolve_config_dir

    return resolve_config_dir(Path(root_dir).expanduser().resolve())


def _active_file(root_dir: str | Path) -> Path:
    """Path of the active-session pointer inside the config dir."""
    return _config_dir(root_dir) / "active_session"


def get_active_session(root_dir: str | Path) -> str | None:
    """Read the converged-upon active session id (any browser lands here).

    :param root_dir: Project root.
    :return: Active session id, or None when never set.
    """
    try:
        text = _active_file(root_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def set_active_session(root_dir: str | Path, session_id: str) -> None:
    """Point the project at the most recently used session.

    Best-effort: a lost pointer only costs convergence, never chat.

    :param root_dir: Project root.
    :param session_id: Session identifier to mark active.
    """
    try:
        target = _active_file(root_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(session_id, encoding="utf-8")
    except OSError as exc:
        logger.warning("Active session pointer unwritable: %s", exc)


def available() -> bool:
    """Whether the harness conversation store imports cleanly."""
    return SqliteConversationStore is not None


# ---------------------------------------------------------------------------
# Conversation persistence (pydantic side, converted at the edge)
#
# The harness store above carries the *messages*, which is enough to
# display and search a session but not to continue one: a Conversation
# also carries the running usage and the conversation_id. Continuing
# from messages alone makes every turn's UsageLimits budget start over
# from zero, so the authoritative record is kept here as JSON and fed
# back through dispatch_request(usage=..., conversation_id=...).
# ---------------------------------------------------------------------------

@contextmanager
def _conversation_connection(root_dir: str | Path) -> Any:
    """Short-lived SQLite connection for conversation JSON (WAL enabled).

    Deliberately NOT cached: these run under ``asyncio.to_thread``,
    whose pool picks an arbitrary worker per call, and a sqlite3
    connection defaults to ``check_same_thread=True``. A cached
    connection therefore failed with "SQLite objects created in a
    thread can only be used in that same thread" on whichever call
    landed on a different worker than the one that created it.
    Opening per operation matches how the harness's own conversation
    store works and removes the thread affinity entirely.

    :param root_dir: Project root selecting the database.
    :return: Context manager yielding an open connection.
    """
    import sqlite3

    database = _config_dir(root_dir) / "conversations.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS conversations ("
            "id TEXT PRIMARY KEY, json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_conversation(session_id: str, conversation_json: str) -> None:
    """Store a session's Conversation JSON (upsert, best-effort).

    :param session_id: Session identifier.
    :param conversation_json: Output of ConversationTypeAdapter.dump_json.
    """
    try:
        with _conversation_connection(session_id) as conn:
            conn.execute(
                "INSERT INTO conversations (id, json, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "json=excluded.json, updated_at=excluded.updated_at",
                (session_id, conversation_json, datetime.now(UTC).isoformat()),
            )
    except Exception as exc:
        logger.warning("Conversation save skipped: %s", exc)


def load_conversation(session_id: str) -> Any:
    """Load a session's Conversation, or None when absent/unreadable.

    :param session_id: Session identifier.
    :return: A ``Conversation`` instance, or None.
    """
    try:
        from pydantic_ai import ConversationTypeAdapter

        with _conversation_connection(session_id) as conn:
            row = conn.execute(
                "SELECT json FROM conversations WHERE id=?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return ConversationTypeAdapter.validate_json(row[0])
    except Exception as exc:
        logger.debug("Conversation load skipped: %s", exc)
        return None


def get_store(root_dir: str | Path) -> Any:
    """Return the SQLite conversation store for a project root.

    :param root_dir: Project root (database lives in the resolved
        config directory, e.g. ``.berg-agents/chat_sessions.db``).
    :return: Shared ``SqliteConversationStore`` for the root.
    :raises ImportError: When the harness store is unavailable.
    """
    if not available():
        raise ImportError("pydantic_ai_harness step_persistence unavailable")
    key = str(_config_dir(root_dir))
    store = _stores.get(key)
    if store is None:
        database = _config_dir(root_dir) / "chat_sessions.db"
        store = SqliteConversationStore(database=database)
        _stores[key] = store
    return store


def project_name(root_dir: str | Path) -> str:
    """Display name for a project root (its directory name)."""
    return Path(root_dir).expanduser().resolve().name or "project"


def summary_to_dict(summary: Any) -> dict[str, Any]:
    """Serialize a conversation summary for the sessions API."""
    return {
        "id": summary.id,
        "title": summary.title,
        "subtitle": summary.subtitle,
        "workspace": summary.workspace,
        "updated_at": summary.updated_at.isoformat(),
        "message_count": summary.message_count,
        "model": summary.model,
        "outcome": summary.outcome}


def coerce_session_id(raw: Any) -> str:
    """Validate a client session id, minting one when unusable."""
    if isinstance(raw, str) and _ID_RE.fullmatch(raw):
        return raw
    return uuid4().hex


def first_user_text(ui_messages: Any) -> str:
    """First user text in a Vercel AI message list (for subtitles)."""
    if not isinstance(ui_messages, list):
        return ""
    for msg in ui_messages:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        for part in msg.get("parts") or []:
            if (
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
                and part["text"].strip()
            ):
                return part["text"].strip()[:80]
    return ""


async def ensure_session(
    store: Any,
    session_id: str,
    *,
    workspace: str,
    subtitle: str = "",
    model: str | None = None,
) -> Any:
    """Fetch a session, creating it (numbered per project) when missing.

    :param store: Conversation store.
    :param session_id: Stable session identifier.
    :param workspace: Project display name recorded on the session.
    :param subtitle: First user text recorded as subtitle.
    :param model: Active model recorded on the session.
    :return: The existing or new ``ConversationSummary``.
    """
    try:
        saved = await store.get(conversation_id=session_id)
        return saved.summary
    except LookupError:
        pass
    existing = await store.listing(limit=10000)
    seq = len(existing) + 1
    date = datetime.now().date().isoformat()
    summary = ConversationSummary(
        id=session_id,
        workspace=workspace,
        title=f"{workspace} #{seq} · {date}",
        subtitle=subtitle,
        model=model,
    )
    # NOTE: A fresh summary has revision 0, which save() requires for
    # inserts — but save() also needs messages; seed with none and let
    # the first completed turn write the transcript.
    await store.save(summary=summary, messages=[])
    saved = await store.get(conversation_id=session_id)
    logger.info("Session created: %s (%s)", session_id, summary.title)
    return saved.summary


async def record_turn(store: Any, session_id: str, messages: Any) -> Any | None:
    """Persist a completed turn's messages (one CAS retry on conflict).

    :param store: Conversation store.
    :param session_id: Session identifier.
    :param messages: ``ModelMessage`` list (e.g. ``result.all_messages()``).
    :return: Updated summary, or None when the session is gone/failing.
    """
    from pydantic_ai_harness.step_persistence.conversations import (
        ConversationConflict,
    )

    try:
        saved = await store.get(conversation_id=session_id)
    except LookupError:
        logger.warning("Session vanished, skipping save: %s", session_id)
        return None
    for _ in range(2):
        try:
            return await store.save(summary=saved.summary, messages=messages)
        except ConversationConflict:
            # NOTE: Another tab/process wrote first — reload fresh
            # revision and retry once, then give up loudly in logs.
            logger.warning("Session write conflict, retrying: %s", session_id)
            try:
                saved = await store.get(conversation_id=session_id)
            except LookupError:
                return None
    return None
