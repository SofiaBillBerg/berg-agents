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

"""Session compaction endpoint — the ``/compact`` command.

The client owns history: every turn re-sends the whole transcript, and
the adapter rebuilds context from the messages it is sent. So a durable
compaction has to rewrite the *stored* messages, and the client has to
reload the session afterwards — otherwise the next turn re-sends the long
version and the compaction is undone.

The strategy is shared with the live path by design
(:func:`~berg_agents.capabilites.context_capabilities.build_compaction`),
so the interactive command and automatic compaction can never disagree
about what compaction means.
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.providers.models import resolve_model_string
from berg_agents.ui import session_store
from berg_agents.ui.schemas import SessionCompactRequest
from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


def register_compaction_routes(
    router: APIRouter, *, sessions: SessionManager
) -> None:
    """Register the session-compaction endpoint.

    :param router: Router to attach endpoints to.
    :param sessions: Session store (root dir + active model).
    """

    @router.post("/api/sessions/{session_id}/compact")
    async def compact_session_endpoint(
        session_id: str, request: SessionCompactRequest | None = None
    ) -> dict[str, Any]:
        """Compact one session's stored history (the /compact command).

        :param session_id: Session to compact.
        :param request: Optional ``focus`` steering the summarizer.
        :return: Dict with before/after counts and token estimates.
        :raises HTTPException: 404 for an unknown session, 409 on a
            write conflict, 502 when the strategy cannot run.
        """
        focus = (request.focus if request is not None else None) or None
        store = session_store.get_store(sessions._harness_root_dir())
        try:
            # The session tracks a bare model name ("bonsai-2:9b");
            # the summarizer and tokenizer need the provider-qualified
            # form ("ollama:bonsai-2:9b").
            result = await session_store.compact_session(
                store,
                session_id,
                model=resolve_model_string(sessions.active_model),
                focus=focus,
            )
        except LookupError:
            raise HTTPException(
                status_code=404, detail=f"Unknown session '{session_id}'."
            ) from None
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # summarizer failure, capacity, timeout...
            logger.warning(
                "Compact %s failed: %s", session_id, exc, exc_info=True
            )
            raise HTTPException(
                status_code=502, detail=f"Compaction failed: {exc}"
            ) from exc
        summary = result.get("summary")
        return {
            "session_id": session_id,
            "before": result.get("before", 0),
            "after": result.get("after", 0),
            "tokens_before": result.get("tokens_before"),
            "tokens_after": result.get("tokens_after"),
            "summary": (
                session_store.summary_to_dict(summary)
                if summary is not None
                else None
            )}
