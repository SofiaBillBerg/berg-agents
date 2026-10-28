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

"""HTTP endpoints for the berg_agents web API.

All routes consumed by the Next.js frontend (``webapp/app``).
The streaming chat endpoint uses :class:`~pydantic_ai.ui.vercel_ai.VercelAIAdapter`
for native Vercel AI SSE protocol - no manual event-loop / SSE translation needed.
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.harness import Harness
from berg_agents.ui.route_handlers.agents import register_agent_routes
from berg_agents.ui.route_handlers.chat import register_chat_routes
from berg_agents.ui.route_handlers.context import register_context_routes
from berg_agents.ui.route_handlers.plugins import register_plugin_routes
from berg_agents.ui.route_handlers.providers import register_provider_routes
from berg_agents.ui.route_handlers.router_stats import (
    register_router_stats_routes,
)
from berg_agents.ui.route_handlers.sessions import register_session_routes
from berg_agents.ui.route_handlers.tools import register_tool_routes
from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter

logger = logging.getLogger(__name__)


#: Give up on a chat stream after this many consecutive empty responses.
def create_router(
    harness: Harness,
    sessions: SessionManager,
    *,
    providers: list[dict[str, Any]],
) -> APIRouter:
    """Build the API router with injected dependencies.

    :param harness: Shared harness (single instance per app).
    :param sessions: Session store (needed for model override in chat).
    :param providers: Configured provider/model pairs.
    :return: Configured APIRouter.
    """
    router = APIRouter()

    register_agent_routes(router, harness=harness, sessions=sessions)
    register_chat_routes(router, harness=harness, sessions=sessions)
    register_context_routes(router, sessions=sessions)
    register_router_stats_routes(router, harness=harness)
    register_plugin_routes(router, sessions=sessions)
    register_session_routes(router, sessions=sessions)
    register_tool_routes(router, harness=harness, sessions=sessions)

    register_provider_routes(router, sessions, providers)
    return router
