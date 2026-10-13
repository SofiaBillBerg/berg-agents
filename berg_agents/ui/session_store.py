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

import logging
import re
from datetime import datetime
from pathlib import Path
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


def _active_file(root_dir: str | Path) -> Path:
    """Path of the active-session pointer for a project root."""
    return (
        Path(root_dir).expanduser().resolve()
        / ".berg_agents"
        / "active_session"
    )


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


def get_store(root_dir: str | Path) -> Any:
    """Return the SQLite conversation store for a project root.

    :param root_dir: Project root (database lives in ``.berg_agents/``).
    :return: Shared ``SqliteConversationStore`` for the root.
    :raises ImportError: When the harness store is unavailable.
    """
    if not available():
        raise ImportError("pydantic_ai_harness step_persistence unavailable")
    key = str(Path(root_dir).expanduser().resolve())
    store = _stores.get(key)
    if store is None:
        database = Path(key) / ".berg_agents" / "chat_sessions.db"
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
