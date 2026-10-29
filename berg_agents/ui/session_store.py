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

"""Server-side chat sessions (one global database).

Local-storage sessions are per-browser-profile. This module persists the authoritative copy
server-side in SQLite, following the Pydantic pattern of storing the
framework side and converting at the edge: ``ModelMessages`` in,
``dump_messages`` UI JSON out.

**One database, globally found.** Sessions are user-owned, not
repo-owned: a conversation started while working on one project must
still open after the user switches projects, so there is deliberately
no per-project copy. Each session records the ``workspace``
(project display name) it belongs to, and the seq in a default title
is counted within that workspace.

Session identity is a stable id (client thread id or minted uuid) that
never changes — a session resumed days later keeps its id. Only the
*title* evolves: ``<project> #<seq> · <date>`` at creation, refined to
``<project> #<seq> · <date> · <intent>`` once the first real user
message lands, so a session resumed across days still reads naturally.
Renames are explicit user titles and always win.
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

#: The one session database, always under the **global** config dir.
SESSION_DB_NAME = "sessions.db"

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

#: Cache keyed by the global dir (one cache entry, by design).
_stores: dict[str, Any] = {}


def _global_session_dir() -> Path:
    """The global config dir — sessions live here, once, for every project.

    Deliberately NOT :func:`resolve_config_dir`: resolving would pick a
    project's ``.berg-agents/`` when one exists, which put a copy of the
    user's sessions inside each repo and hid conversations from every
    other project. ``BERG_AGENTS_CONFIG_DIR`` still overrides the
    location when set (a deployment running with its own root).
    """
    from berg_agents.config.paths import global_config_dir

    return global_config_dir()


def _session_database() -> Path:
    """Path of the one global session database (created by callers)."""
    return _global_session_dir() / SESSION_DB_NAME


def _config_dir(root_dir: str | Path) -> Path:
    """Deprecated alias kept only for project-scoped non-session state.

    Sessions must use :func:`_global_session_dir` instead — see the
    module docstring. This resolver is for other per-project config.
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
        logger.warning(
            "Active session pointer unwritable: %s", exc, exc_info=True
        )


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
def _conversation_connection() -> Any:
    """Short-lived SQLite connection for conversation JSON (WAL enabled).

    Deliberately NOT cached: these run under ``asyncio.to_thread``,
    whose pool picks an arbitrary worker per call, and a sqlite3
    connection defaults to ``check_same_thread=True``. A cached
    connection therefore failed with "SQLite objects created in a
    thread can only be used in that same thread" on whichever call
    landed on a different worker than the one that created it.
    Opening per operation matches how the harness's own conversation
    store works and removes the thread affinity entirely.

    The table is named ``conversation_records`` — the harness
    ``SqliteConversationStore`` owns a *different* ``conversations``
    table in the very same file, and sharing the name there was a
    schema collision waiting to happen.

    :return: Context manager yielding an open connection.
    """
    import sqlite3

    database = _session_database()
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS conversation_records ("
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
        with _conversation_connection() as conn:
            conn.execute(
                "INSERT INTO conversation_records (id, json, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "json=excluded.json, updated_at=excluded.updated_at",
                (session_id, conversation_json, datetime.now(UTC).isoformat()),
            )
    except Exception as exc:
        # Usage/usage-budget carry-over lives here: a silent failure
        # resets the budget every turn, so it is never debug-level.
        logger.warning(
            "Conversation save skipped (usage will not carry over): %s",
            exc,
            exc_info=True,
        )


def load_conversation(session_id: str) -> Any:
    """Load a session's Conversation, or None when absent/unreadable.

    :param session_id: Session identifier.
    :return: A ``Conversation`` instance, or None.
    """
    try:
        from pydantic_ai import ConversationTypeAdapter

        with _conversation_connection() as conn:
            row = conn.execute(
                "SELECT json FROM conversation_records WHERE id=?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return ConversationTypeAdapter.validate_json(row[0])
    except Exception as exc:
        logger.warning("Conversation load skipped: %s", exc, exc_info=True)
        return None


def get_store(root_dir: str | Path | None = None) -> Any:
    """Return the one global SQLite conversation store.

    :param root_dir: Ignored for placement (kept for signature
        compatibility). Sessions are global, not per-project — see the
        module docstring.
    :return: Shared ``SqliteConversationStore`` backed by
        ``~/.berg-agents/sessions.db``.
    :raises ImportError: When the harness store is unavailable.
    """
    if not available():
        raise ImportError("pydantic_ai_harness step_persistence unavailable")
    database = _session_database()
    key = str(database)
    store = _stores.get(key)
    if store is None:
        database.parent.mkdir(parents=True, exist_ok=True)
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


#: Utterances that say nothing about intent — never used as a slug.
_GREETINGS = frozenset({
    "hi",
    "hii",
    "hiii",
    "hiya",
    "hey",
    "heyy",
    "hello",
    "helloo",
    "yo",
    "sup",
    "test",
    "testing",
    "ok",
    "okay",
    "yes",
    "no",
    "thanks",
    "thank you",
    "please",
    "?"})

#: Words that carry no topic and only pad a slug.
_FILLER = frozenset({
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "then",
    "else",
    "please",
    "can",
    "you",
    "your",
    "could",
    "would",
    "should",
    "just",
    "with",
    "for",
    "from",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "do",
    "does",
    "did",
    "i",
    "me",
    "my",
    "mine",
    "we",
    "us",
    "our",
    "let's",
    "lets",
    "want",
    "need",
    "like",
    "some",
    "any",
    "all",
    "not"})


def intent_slug(text: str, *, max_words: int = 4, max_chars: int = 40) -> str:
    """A short readable slug from the first meaningful user message.

    Greetings ("hi", "hello", "test") are skipped — a session's title
    should say what the session is *about*, which "hi" never does.
    Filler words are dropped so the slug is the topic, not the phrasing.

    :param text: First user text (as recorded in a subtitle).
    :param max_words: Maximum words to keep.
    :param max_chars: Maximum slug length after joining.
    :return: Slug such as ``transcript autosave``; empty when nothing
        meaningful remains (a pure greeting, or no text).
    """
    candidate = (text or "").strip().lower()
    if not candidate:
        return ""
    # Words first, so a greeting can be recognised even when filler
    # follows it ("hi there", "hello again").
    words = re.findall(r"[a-z0-9]+", candidate)
    if not words:
        return ""
    # Leading greeting + filler carry no intent: drop the leading run of
    # them so the slug starts at the first real content word.
    while words and words[0] in _GREETINGS:
        words = words[1:]
        # Then drop any filler immediately following the greeting.
        while words and words[0] in _FILLER:
            words = words[1:]
    if not words:
        return ""
    kept = [w for w in words if w not in _FILLER and len(w) > 1][:max_words]
    slug = " ".join(kept).strip()
    if len(slug) > max_chars:
        slug = slug[:max_chars].rsplit(" ", 1)[0].strip()
    return slug


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


async def refine_session_title(
    store: Any,
    session_id: str,
    subtitle: str,
    workspace: str,
) -> str | None:
    """Append an intent slug to a generated title, once, after creation.

    Called after ``ensure_session`` with the first user text in hand:
    the session is created with no text yet, so ``#N · date`` is all it
    can honestly carry at that point. This refines it in place, without
    touching the id, and never overwrites a title the user renamed.

    :param store: Conversation store.
    :param session_id: Session to refine.
    :param subtitle: First user text (the intent source).
    :param workspace: Project display name (guard for the right session).
    :return: The new title, or None when nothing needed refining.
    """
    slug = intent_slug(subtitle)
    if not slug:
        return None
    try:
        saved = await store.get(conversation_id=session_id)
    except LookupError:
        return None
    summary = saved.summary
    if summary.workspace != workspace:
        return None
    # A renamed title is the user's; never overwrite it.
    if not summary.title.startswith(f"{workspace} #"):
        return None
    if f"· {slug}" in summary.title:
        return None  # Already refined with this intent.
    new_title = f"{summary.title} · {slug}"
    try:
        await store.name(
            source=summary, title=new_title, subtitle=summary.subtitle
        )
    except Exception as exc:
        logger.warning("Session title refine skipped: %s", exc, exc_info=True)
        return None
    return new_title


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
    # The database is global, so numbering must count within this
    # workspace — otherwise a project's second session is titled #14
    # because the user has sessions from three other projects.
    existing = await store.listing(limit=10000)
    seq = sum(1 for s in existing if s.workspace == workspace) + 1
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
