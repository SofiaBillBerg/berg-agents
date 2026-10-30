# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
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

"""Session endpoints.

Extracted from ``create_router`` — one concern per module. Server-side
chat sessions: list, create, current, get (restore), rename, delete.
"""

from __future__ import annotations

from typing import Any

from berg_agents.ui import context_usage, projects, transcripts
from berg_agents.ui.schemas import SessionCreateRequest, SessionRenameRequest
from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter, HTTPException


def _unique_ui_message_id(msg: Any, role: str, index: int) -> str:
    """Message ids for restored sessions (React keys + SDK identity).

    The adapter default restores the original client id per ModelMessage —
    but one ModelRequest carrying both system and user parts dumps to TWO
    UIMessages with that same id, which React rejects as duplicate keys.
    Namespacing by role keeps ids deterministic (stable across reloads)
    and unique.
    """
    # NOTE: Reuses the adapter default, then disambiguates. Same reader
    # the chat path uses, so restored ids stay consistent with live ones.
    from pydantic_ai.ui.vercel_ai._adapter import _generate_message_id  # ruff: ignore[import-private-name]

    return f"{_generate_message_id(msg, role, index)}-{role}-{index}"


def register_session_routes(
    router: APIRouter, *, sessions: SessionManager
) -> None:
    """Register server-side chat session endpoints.

    :param router: Router to attach endpoints to.
    :param sessions: Session store (root dir + active provider/model).
    """

    @router.get("/api/sessions")
    async def list_sessions(q: str = "", limit: int = 100) -> dict[str, Any]:
        """List server-side chat sessions (newest first, searchable).

        The authoritative session list for every browser: unlike the
        localStorage snapshots, these survive profile switches.

        :param q: Full-text filter over titles and transcripts.
        :param limit: Max sessions returned.
        :return: Dict with ``sessions`` summaries.
        """
        from berg_agents.ui import session_store

        store = session_store.get_store(sessions._harness_root_dir())
        found = await store.listing(
            query=q or "", limit=max(1, min(limit, 200))
        )
        return {"sessions": [session_store.summary_to_dict(s) for s in found]}

    @router.get("/api/sessions/current")
    async def get_current_session() -> dict[str, Any]:
        """Return the converged-upon active session id (may be null).

        Fresh browsers adopt this instead of minting divergent sessions,
        so every window lands on the same conversation.

        :return: Dict with ``id`` (or null).
        """
        from berg_agents.ui import session_store

        return {
            "id": session_store.get_active_session(sessions._harness_root_dir())
        }

    @router.get("/api/context/usage")
    async def get_context_usage(
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Live context-window usage for a session (the compaction gauge).

        Answers the question "how full is my context, and is compaction
        coming?" — which the user otherwise only discovers when their
        history is suddenly shorter. ``ReportContextUsage`` emits the
        reading; this serves the latest one.

        :param session_id: Session to report on; defaults to the active
            session when omitted.
        :return: Dict with the reading, or ``{"usage": null}`` when this
            session has not made a model request yet.
        """
        from berg_agents.ui import context_usage, session_store

        target = session_id or session_store.get_active_session(
            sessions._harness_root_dir()
        )
        usage = context_usage.latest(target)
        return {
            "session_id": target,
            "usage": {
                **usage,
                # A session id alone is not usage: report the session's
                # model so the gauge can name what it is measuring.
                "model": sessions.active_model}
            if usage
            else None}

    @router.post("/api/sessions/current")
    async def set_current_session(request: dict[str, Any]) -> dict[str, Any]:
        """Point the project at one session (restore / new chat / send).

        :param request: Mapping with the session ``id``.
        :return: Dict with the adopted ``id``.
        :raises HTTPException: 404 for unknown session ids.
        """
        from berg_agents.ui import session_store

        raw = request.get("id") if isinstance(request, dict) else None
        session_id = session_store.coerce_session_id(raw)
        if raw != session_id:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{raw}'."
            )
        root = sessions._harness_root_dir()
        store = session_store.get_store(root)
        try:
            await store.get(conversation_id=session_id)
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        session_store.set_active_session(root, session_id)
        return {"id": session_id}

    @router.post("/api/sessions")
    async def create_session(
        request: SessionCreateRequest | None = None,
    ) -> dict[str, Any]:
        """Create a server-side chat session.

        Titles default to ``<project> #<seq> · <date>`` (never the first
        "hello"); pass an explicit title or rename later.

        :param request: Optional explicit title.
        :return: The created session summary.
        """
        from berg_agents.ui import session_store

        root = sessions._harness_root_dir()
        store = session_store.get_store(root)
        session_id = session_store.coerce_session_id(None)
        summary = await session_store.ensure_session(
            store,
            session_id,
            workspace=session_store.project_name(root),
            model=sessions.active_model,
        )
        if request and request.title and request.title.strip():
            await store.name(
                source=summary,
                title=request.title.strip()[:80],
                manual=True,
            )
            summary = (await store.get(conversation_id=session_id)).summary
        session_store.set_active_session(root, session_id)
        return session_store.summary_to_dict(summary)

    @router.get("/api/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        """Load one session with UI messages for restoring in chat.

        Converts the stored framework messages at the edge
        (``dump_messages``) for the hook to consume.

        :param session_id: Session identifier.
        :return: Summary plus ``messages`` in Vercel AI UI shape.
        :raises HTTPException: 404 for unknown sessions.
        """
        from berg_agents.ui import session_store
        from pydantic_ai.ui.vercel_ai import VercelAIAdapter

        store = session_store.get_store(sessions._harness_root_dir())
        try:
            saved = await store.get(conversation_id=session_id)
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        ui_messages = VercelAIAdapter.dump_messages(
            saved.messages,
            sdk_version=6,
            generate_message_id=_unique_ui_message_id,
        )
        return {
            "session": session_store.summary_to_dict(saved.summary),
            "messages": [m.model_dump(mode="json") for m in ui_messages]}

    @router.patch("/api/sessions/{session_id}")
    async def rename_session(
        session_id: str, request: SessionRenameRequest
    ) -> dict[str, Any]:
        """Rename a session (explicit user title, wins over generated).

        :param session_id: Session identifier.
        :param request: New title.
        :return: Updated session summary.
        :raises HTTPException: 404 for unknown sessions.
        """
        from berg_agents.ui import session_store

        if not request.title.strip():
            raise HTTPException(
                status_code=400, detail="Title must not be blank."
            )
        store = session_store.get_store(sessions._harness_root_dir())
        try:
            saved = await store.get(conversation_id=session_id)
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        await store.name(
            source=saved.summary,
            title=request.title.strip()[:80],
            manual=True,
        )
        updated = await store.get(conversation_id=session_id)
        return session_store.summary_to_dict(updated.summary)

    @router.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, Any]:
        """Delete a server-side session and its transcript.

        :param session_id: Session identifier.
        :return: Dict with ``ok``.
        :raises HTTPException: 404 for unknown sessions, 409 when busy.
        """
        from berg_agents.ui import session_store
        from pydantic_ai_harness.step_persistence.conversations import (
            ConversationConflict,
        )

        store = session_store.get_store(sessions._harness_root_dir())
        try:
            saved = await store.get(conversation_id=session_id)
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        try:
            await store.delete(source=saved.summary)
        except ConversationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # The durable JSONL transcript goes with the session: deleting
        # one and leaving the other would be a two-copies problem.
        transcripts.delete_transcript(
            session_id,
            projects.resolve_project(sessions._harness_root_dir()),
        )
        # And the gauge's last reading goes with it, so a reused id
        # cannot inherit a stale number.
        context_usage.forget(session_id)
        return {"ok": True}
