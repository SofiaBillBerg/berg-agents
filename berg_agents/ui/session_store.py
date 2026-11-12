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

#: Session ids must stay narrow (they become filenames/keys). The cap is
#: sized for a id that names its project: a 32-character unique part, the
#: ``__`` separator, and a project id (itself capped at 64) — 128 keeps the
#: suffix from ever being the reason an otherwise valid id is rejected.
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:-]{0,127}")

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


# ---------------------------------------------------------------------------
# Runaway-guard progress (tool calls since the user last intervened)
#
# The guard counts tool calls the agent executes without the user getting a
# say. The count must outlive the agent object, which is rebuilt per request,
# so it lives here beside the conversation record. It is reset when the agent
# *yields control* (turn finished, run paused, HITL decision, Stop) and not
# when the user merely types while the agent is still working.
# ---------------------------------------------------------------------------


def _guard_connection() -> Any:
    """Short-lived connection for runaway-guard progress rows.

    Opened per operation for the same reason as
    :func:`_conversation_connection`: the callers run under
    ``asyncio.to_thread`` and a sqlite3 connection is thread-affine.

    :return: Context manager yielding an open connection.
    """
    import sqlite3

    database = _session_database()
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS guard_progress ("
        "session_id TEXT PRIMARY KEY, "
        "tool_calls INTEGER NOT NULL DEFAULT 0, "
        "nudged INTEGER NOT NULL DEFAULT 0, "
        "updated_at TEXT NOT NULL)"
    )
    return conn


def read_guard_progress(session_id: str) -> tuple[int, bool]:
    """Read how far a session has run without user intervention.

    :param session_id: Session identifier.
    :return: ``(tool_calls, nudged)`` - the current count and whether the
        advisory reminder has already fired for this stretch. ``(0, False)``
        when the session has no row yet or the store is unreadable.
    """
    conn = None
    try:
        conn = _guard_connection()
        row = conn.execute(
            "SELECT tool_calls, nudged FROM guard_progress WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return 0, False
        return int(row[0]), bool(row[1])
    except Exception as exc:
        # Best-effort: a lost count only weakens the guard, never chat.
        logger.warning("Guard progress read skipped: %s", exc, exc_info=True)
        return 0, False
    finally:
        if conn is not None:
            conn.close()


def write_guard_progress(
    session_id: str, *, tool_calls: int, nudged: bool
) -> None:
    """Persist a session's guard progress (upsert, best-effort).

    :param session_id: Session identifier.
    :param tool_calls: Tool calls executed since the user last intervened.
    :param nudged: Whether the advisory reminder has fired for this stretch.
    :return: None.
    """
    conn = None
    try:
        conn = _guard_connection()
        conn.execute(
            "INSERT INTO guard_progress "
            "(session_id, tool_calls, nudged, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "tool_calls=excluded.tool_calls, nudged=excluded.nudged, "
            "updated_at=excluded.updated_at",
            (
                session_id,
                tool_calls,
                int(nudged),
                datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Guard progress write skipped: %s", exc, exc_info=True)
    finally:
        if conn is not None:
            conn.close()


def reset_guard_progress(session_id: str) -> None:
    """Reset a session's count - called when the agent yields control.

    :param session_id: Session identifier.
    :return: None.
    """
    conn = None
    try:
        conn = _guard_connection()
        conn.execute(
            "DELETE FROM guard_progress WHERE session_id=?", (session_id,)
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Guard progress reset skipped: %s", exc, exc_info=True)
    finally:
        if conn is not None:
            conn.close()


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


#: Separator between the unique part of a session id and its project suffix.
#: Safe in a filename and in ``_ID_RE``, and it cannot occur in either half.
SESSION_ID_SEPARATOR = "__"


def mint_session_id(project_id: str) -> str:
    """Mint a new session id that names its project.

    ``<uuid-hex>__<project-id>``, for example
    ``7ebcc3c2eb2844a2ad53b4d7a8136656__berg-agents``. The transcript file
    already lives in the project's folder, so the suffix is not what files
    it - it is what keeps the id readable when it travels without that
    context (a database row, a log line, a URL).

    :param project_id: Folder-safe project id (``projects.project_id_for``).
    :return: A fresh, unique session id.
    """
    return f"{uuid4().hex}{SESSION_ID_SEPARATOR}{project_id}"


def split_session_id(session_id: str) -> tuple[str, str | None]:
    """Split a session id into its unique part and project suffix.

    :param session_id: Any session id, suffixed or not.
    :return: ``(unique_part, project_id)``, with ``None`` for a legacy
        bare id that carries no project.
    """
    head, separator, tail = session_id.partition(SESSION_ID_SEPARATOR)
    return (head, tail) if separator and tail else (session_id, None)


def coerce_session_id(raw: Any, project_id: str | None = None) -> str:
    """Validate a client session id, minting one when unusable.

    This is the ONE place a session id comes into existence. A caller that
    knows the project passes it, so a minted id names that project; an
    existing id is returned untouched, which is what lets old bare-uuid
    sessions keep working.

    :param raw: Client-supplied id (any type; only a string can be valid).
    :param project_id: Project the new session belongs to, when known.
    :return: The accepted id, or a newly minted one.
    """
    if isinstance(raw, str) and _ID_RE.fullmatch(raw):
        return raw
    return mint_session_id(project_id or "unknown-project")


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
    store: Any, session_id: str, subtitle: str, workspace: str
) -> str | None:
    """Record the first user text as the subtitle; never touch the title.

    The title is ``project · date`` — the honest thing a session can carry
    before it has any content — so this sets the SUBTITLE to the user's own
    words instead. That is where the topic belongs: the actual first message
    is more informative than any summary of it, and it cannot be wrong the way
    a mangled slug was.

    A title the user renamed is left alone, and so is the subtitle once set,
    so a resumed session keeps what it already shows.

    :param store: Conversation store.
    :param session_id: Session to refine.
    :param subtitle: First user text (the topic to show).
    :param workspace: Project display name (guard for the right session).
    :return: The new subtitle, or None when nothing needed refining.
    """
    text = (subtitle or "").strip()
    if not text:
        return None
    try:
        saved = await store.get(conversation_id=session_id)
    except LookupError:
        return None
    summary = saved.summary
    if summary.workspace != workspace:
        return None
    # Already carrying this topic: a re-render must not churn the row.
    if summary.subtitle.strip() == text:
        return None
    new_subtitle = text[:80]
    try:
        await store.name(
            source=summary, title=summary.title, subtitle=new_subtitle
        )
    except Exception as exc:
        logger.warning("Session title refine skipped: %s", exc, exc_info=True)
        return None
    return new_subtitle


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
    # No sequence number: it counted within the workspace only because the
    # database is global, and it told the user nothing they could act on.
    # Sofia's call, 2026-11-12 — "project and date".
    date = datetime.now().date().isoformat()
    summary = ConversationSummary(
        id=session_id,
        workspace=workspace,
        # "project · date" and nothing else. A sequence number told the user
        # nothing and a slug derived from the first four words of an opening
        # sentence was worse than nothing ("out features look how" was the
        # literal front of a request about packaging). The topic lives in the
        # subtitle, set by refine_session_title from the message itself, and a
        # title the user renames always wins. Sofia's call, 2026-11-12.
        title=f"{workspace} · {date}",
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


async def compact_session(
    store: Any, session_id: str, *, model: str, focus: str | None = None
) -> dict[str, Any]:
    """Compact one session's stored history in place.

    The backend is stateless and the client re-sends the whole
    transcript every turn, so shrinking the *stored* messages is what
    actually carries: the adapter rebuilds context from the messages
    this writes, not from a Conversation object. The caller must then
    make the client reload the session, or the next turn re-sends the
    long version and the compaction is undone.

    :param store: Conversation store holding the session.
    :param session_id: Session to compact.
    :param model: Model id whose context window and tokenizer the
        strategy resolves against.
    :param focus: Optional instruction steering the summarizer.
    :return: Dict with ``before``/``after`` message counts and the
        compacted ``summary`` (None when there was nothing to do).
    :raises LookupError: When the session does not exist.
    """
    from pydantic_ai_harness.step_persistence.conversations import (
        ConversationConflict,
    )

    saved = await store.get(conversation_id=session_id)  # LookupError → 404
    messages = list(saved.messages)
    if not messages:
        return {"before": 0, "after": 0, "summary": saved.summary}

    from berg_agents.capabilities.context_capabilities import build_compaction
    from pydantic_ai_harness.compaction import compact_now

    strategy = build_compaction()
    if strategy is None:
        raise RuntimeError("compaction strategy unavailable")
    tokens_before = _estimate_tokens(messages, model)
    compacted = await compact_now(strategy, messages, model=model, focus=focus)
    if list(compacted) == messages:
        # The strategy declined (history already under target): report
        # honestly rather than claiming a compaction that did nothing.
        return {
            "before": len(messages),
            "after": len(messages),
            "summary": saved.summary,
            "tokens_before": tokens_before,
            "tokens_after": tokens_before}

    for _ in range(2):
        try:
            await store.save(summary=saved.summary, messages=compacted)
            break
        except ConversationConflict:
            logger.warning("Compact write conflict, retrying: %s", session_id)
            try:
                saved = await store.get(conversation_id=session_id)
            except LookupError:
                return {"before": len(messages), "after": len(messages)}
    else:  # pragma: no cover - conflict twice is a busy writer
        logger.warning("Compact gave up after conflict: %s", session_id)
        return {"before": len(messages), "after": len(messages)}

    # `store.save` returns the summary, not the stored record, so read
    # the persisted messages back rather than trusting a local value.
    after = len(list((await store.get(conversation_id=session_id)).messages))
    tokens_after = _estimate_tokens(compacted, model)
    logger.info(
        "Session %s compacted %d → %d messages (~%s → ~%s tokens)",
        session_id,
        len(messages),
        after,
        tokens_before,
        tokens_after,
    )
    return {
        "before": len(messages),
        "after": after,
        "summary": saved.summary,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after}


def _estimate_tokens(messages: Any, model: str = "") -> int:
    """Rough token estimate for a message list (~4 chars per token).

    Deliberately approximate: it exists so a compaction can report
    how much it saved, not to gate one. The strategy's own trigger
    is the authority on whether compaction was needed.
    """
    total = 0
    for message in messages:
        parts = getattr(message, "parts", None) or []
        for part in parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                total += len(content)
            elif content is not None:
                total += len(str(content))
            args = getattr(part, "args", None)
            if args:
                total += len(str(args))
    return total // 4
