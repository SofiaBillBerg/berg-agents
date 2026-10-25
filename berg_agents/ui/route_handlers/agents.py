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

"""Agent catalog endpoints.

Extracted from ``create_router`` — one concern per module. Read-only
views over the shared harness's agent registry, plus the session-scoped
active-agent selection (mirrors ``/api/providers/active``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from berg_agents.core.harness import Harness
from berg_agents.ui.sessions import SessionManager


def register_agent_routes(
    router: APIRouter, *, harness: Harness, sessions: SessionManager
) -> None:
    """Register agent listing/detail + active-selection endpoints.

    Specific (literal) paths are registered before the parameterized
    ``{name}`` path so Starlette's ordered matching picks them up
    (otherwise ``/api/agents/active`` is captured by ``{name}``).
    """

    @router.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        """List all registered agents.

        :return: A list of dictionaries containing information about each agent.
        """
        return harness.get_agent_info()

    # Specific path before the parameterized one (see docstring).
    @router.get("/api/agents/active")
    async def get_active_agent() -> dict[str, Any]:
        """Get the currently active agent (None = default chat agent).

        Mirrors ``/api/providers/active``: a single, session-scoped
        selection the chat turn reads to route to that agent.
        """
        return {"agent": sessions.active_agent}

    @router.put("/api/agents/active")
    async def set_active_agent(body: dict[str, Any]) -> dict[str, Any]:
        """Set the active agent for the chat session.

        :param body: ``{"agent": <name> | null}``.
        :return: The stored selection.
        :raises HTTPException: 404 for an unknown agent.
        """
        name = body.get("agent")
        if name is not None and not isinstance(name, str):
            raise HTTPException(
                status_code=422, detail="agent must be a string or null"
            )
        if isinstance(name, str) and name:
            try:
                harness.get_agent(name)
            except KeyError:
                raise HTTPException(
                    status_code=404, detail=f"Unknown agent '{name}'."
                )
        sessions.active_agent = name if isinstance(name, str) and name else None
        return {"agent": sessions.active_agent}

    @router.get("/api/agents/{name}")
    async def get_agent(name: str) -> dict[str, Any]:
        """Return info for one agent by name.

        :param name: The name of the agent to retrieve.
        :return: A dictionary containing information about the specified agent.
        :raises HTTPException: 404 when the agent name is unknown.
        """
        try:
            return harness.get_agent(name).get_info()
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Agent '{name}' not found"
            ) from None
