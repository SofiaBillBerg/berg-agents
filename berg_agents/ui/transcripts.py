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

"""Durable transcript autosave — append-only JSONL on disk.

The SQLite session store is the live, queryable copy. This module adds
the **human-readable, append-only** copy: one JSONL file per session, so
a transcript survives the database, is greppable, and can be diffed or
read with no tooling at all.

Layout (project-scoped, so one project's sessions group together and a
human can browse by project without knowing any session id):

    ``~/.berg-agents/projects/<project_id>/transcripts/<session_id>.jsonl``

Each file starts with one ``session`` header line, then one line per
message or event::

    {"type":"session","id":"...","project":"berg-agents",
     "project_id":"berg-agents","root_dir":"/home/.../berg-agents",
     "created_at":"2026-10-28T10:00:00+00:00","model":"..."}
    {"type":"message","index":0,"role":"user","sent_at":"...",
     "message":{...ModelMessage JSON...}}
    {"type":"event","event":"hitl","decision":"approve",
     "tool":"write_file","sent_at":"..."}

Messages are stored in pydantic-ai's own ``ModelMessage`` JSON shape —
the durable, non-lossy form — so a transcript rehydrates into a real
conversation without a second (lossy) UI conversion.

Failures are logged *with the exception* and never propagated: a
transcript is a convenience, and losing one must not break a chat turn.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from typing import Any

from berg_agents.ui.projects import ProjectRef

logger = logging.getLogger(__name__)

#: Sub-folder inside a project folder.
_TRANSCRIPTS_DIR = "transcripts"


def transcripts_dir(project: ProjectRef) -> Path:
    """Transcript folder for one project."""
    return project.dir / _TRANSCRIPTS_DIR


def transcript_path(session_id: str, project: ProjectRef) -> Path:
    """Path of one session's transcript file (may not exist yet)."""
    return transcripts_dir(project) / f"{session_id}.jsonl"


def _append_line(path: Path, record: dict[str, Any]) -> bool:
    """Append one JSON line, creating parent folders first."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str))
            handle.write("\n")
        return True
    except Exception as exc:
        logger.warning(
            "Transcript append skipped (%s): %s", path.name, exc, exc_info=True
        )
        return False


def _read_lines(path: Path) -> list[dict[str, Any]]:
    """Read every JSON line; skip (and report) corrupt ones."""
    records: list[dict[str, Any]] = []
    if not path.is_file():
        return records
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Transcript read failed (%s): %s", path.name, exc)
        return records
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except Exception as exc:
            # One bad line must not lose the rest of the transcript.
            logger.warning(
                "Transcript line %d unreadable in %s: %s",
                lineno,
                path.name,
                exc,
            )
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def ensure_transcript(
    session_id: str,
    project: ProjectRef,
    *,
    model: str | None = None,
    created_at: str | None = None,
) -> Path:
    """Create the transcript's header line when the file is new.

    Idempotent: an existing file is left untouched, so a session's
    original ``created_at`` is never rewritten.

    :param session_id: Stable session identifier.
    :param project: Resolved project (drives folder + header metadata).
    :param model: Model active when the session started.
    :param created_at: Explicit timestamp for a session that already
        existed (e.g. restored from SQLite); now when omitted.
    :return: The transcript file path.
    """
    path = transcript_path(session_id, project)
    if path.is_file():
        return path
    _append_line(
        path,
        {
            "type": "session",
            "id": session_id,
            "project": project.name,
            "project_id": project.id,
            "root_dir": project.root_dir,
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "model": model or ""},
    )
    return path


def _dump_messages(messages: Any) -> list[tuple[str | None, dict[str, Any]]]:
    """Serialise ModelMessages to (kind, json-dict) pairs.

    :class:`ModelRequest`/:class:`ModelResponse` are **not** Pydantic
    models and have no ``model_dump`` — the first version of this module
    found that out in the live UI, which wrote a header and no messages.
    Use pydantic-ai's own adapter, which round-trips through JSON.
    """
    from pydantic_ai import ModelMessagesTypeAdapter

    items = list(messages)
    if not items:
        return []
    kinds: list[str | None] = [str(getattr(m, "kind", None)) for m in items]
    try:
        payload = ModelMessagesTypeAdapter.dump_python(items)
        dumped: list[dict[str, Any]] = (
            list(payload) if isinstance(payload, list) else [payload]
        )
        if len(dumped) == len(items):
            return list(zip(kinds, dumped, strict=True))
    except Exception as exc:
        logger.warning("Transcript batch dump failed, per-message: %s", exc)
    # Per-message fallback: one undumpable message must not drop the rest.
    out: list[tuple[str | None, dict[str, Any]]] = []
    for item in items:
        try:
            one = ModelMessagesTypeAdapter.dump_python([item])
            out.append((str(getattr(item, "kind", None)), one[0]))
        except Exception as exc:
            logger.warning(
                "Transcript message skipped (%s): %s",
                type(item).__name__,
                exc,
            )
    return out


def _message_signature(payload: dict[str, Any]) -> str:
    """Stable identity for one serialized message.

    Content-based, not positional: the SQLite store normalizes messages
    (it merges a request-only block into its neighbour), so its order and
    count differ from ``AgentRunResult.all_messages()``. Comparing counts
    therefore drifts and drops the newest user prompt — comparing content
    does not.

    :param payload: Serialized ``ModelMessage`` dict.
    :return: Hex digest identifying this message's content.
    """
    import hashlib

    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def append_new_messages(
    session_id: str,
    project: ProjectRef,
    messages: Any,
) -> int:
    """Append only messages the transcript does not already hold.

    Deduplicates on :func:`_message_signature`, so re-running a turn,
    a turn whose history was rewritten by compaction, or the store's own
    normalization never duplicates a line. Memory snapshots repeat
    verbatim every turn and are correctly skipped as already-present.

    :param session_id: Stable session identifier.
    :param project: Resolved project.
    :param messages: Iterable of pydantic-ai ``ModelMessage`` objects.
    :return: Number of message lines written.
    """
    existing = {
        _message_signature(m)
        for m in read_transcript(session_id, project)["messages"]
        if isinstance(m, dict)
    }
    path = ensure_transcript(session_id, project)
    sent_at = datetime.now(UTC).isoformat()
    written = 0
    for kind, payload in _dump_messages(messages):
        signature = _message_signature(payload)
        if signature in existing:
            continue
        existing.add(signature)
        if _append_line(
            path,
            {
                "type": "message",
                "index": written,
                "role": kind or "unknown",
                "sent_at": sent_at,
                "message": payload},
        ):
            written += 1
    return written


def append_messages(
    session_id: str,
    project: ProjectRef,
    messages: Any,
    *,
    start_index: int = 0,
) -> int:
    """Append one JSONL line per message; return how many landed.

    :param session_id: Stable session identifier.
    :param project: Resolved project.
    :param messages: Iterable of pydantic-ai ``ModelMessage`` objects
        (e.g. ``result.all_messages()``).
    :param start_index: Index of the first message written; the cursor
        for a later incremental read.
    :return: Number of message lines written.
    """
    path = ensure_transcript(session_id, project)
    sent_at = datetime.now(UTC).isoformat()
    written = 0
    for offset, (kind, payload) in enumerate(_dump_messages(messages)):
        if _append_line(
            path,
            {
                "type": "message",
                "index": start_index + offset,
                "role": kind or "unknown",
                "sent_at": sent_at,
                "message": payload},
        ):
            written += 1
    return written


def append_event(
    session_id: str,
    project: ProjectRef,
    event: str,
    **fields: Any,
) -> bool:
    """Append a non-message event line (e.g. a HITL decision).

    :param session_id: Stable session identifier.
    :param project: Resolved project.
    :param event: Event name, e.g. ``hitl``.
    :param fields: Extra fields merged into the record
        (``decision``, ``tool``, ``message_index``, ...).
    :return: True when the line was written.
    """
    path = ensure_transcript(session_id, project)
    record: dict[str, Any] = {
        "type": "event",
        "event": event,
        "sent_at": datetime.now(UTC).isoformat()}
    record.update(fields)
    return _append_line(path, record)


def read_transcript(session_id: str, project: ProjectRef) -> dict[str, Any]:
    """Read one transcript: its header, messages, and events.

    :param session_id: Stable session identifier.
    :param project: Resolved project.
    :return: Dict with ``path``, ``exists``, ``session`` (header or
        None), ``messages`` (framework JSON list) and ``events``. An
        absent file yields empty lists rather than an error.
    """
    path = transcript_path(session_id, project)
    records = _read_lines(path)
    header = next((r for r in records if r.get("type") == "session"), None)
    messages = [r.get("message") for r in records if r.get("type") == "message"]
    events = [r for r in records if r.get("type") == "event"]
    return {
        "path": str(path),
        "exists": path.is_file(),
        "session": header,
        "messages": messages,
        "events": events}


def delete_transcript(session_id: str, project: ProjectRef) -> bool:
    """Delete one session's transcript file (best-effort).

    :param session_id: Stable session identifier.
    :param project: Resolved project.
    :return: True when a file was removed.
    """
    path = transcript_path(session_id, project)
    try:
        if path.is_file():
            path.unlink()
            return True
    except Exception as exc:
        logger.warning("Transcript delete skipped (%s): %s", path.name, exc)
    return False


def list_transcripts(project: ProjectRef) -> list[dict[str, Any]]:
    """Summaries of one project's transcripts, newest first.

    :param project: Resolved project.
    :return: One dict per file with ``session_id``, ``path``,
        ``created_at``, ``message_count`` and ``event_count``.
    """
    folder = transcripts_dir(project)
    if not folder.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.jsonl")):
        records = _read_lines(path)
        header = next((r for r in records if r.get("type") == "session"), {})
        summaries.append({
            "session_id": path.stem,
            "path": str(path),
            "created_at": header.get("created_at"),
            "message_count": sum(
                1 for r in records if r.get("type") == "message"
            ),
            "event_count": sum(1 for r in records if r.get("type") == "event")})
    summaries.sort(key=lambda s: s["path"], reverse=True)
    return summaries
