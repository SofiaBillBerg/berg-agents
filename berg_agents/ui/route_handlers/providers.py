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

"""Provider listing and selection endpoints.

Extracted from ``create_router`` — one concern per module. The active
provider/model pair lives on the injected ``SessionManager``.
"""

from __future__ import annotations

from typing import Any

from berg_agents.ui.schemas import (
    ActiveProvider,
    ProviderInfo,
    ProviderListResponse,
)
from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter


def register_provider_routes(
    router: APIRouter, sessions: SessionManager, providers: list[dict[str, Any]]
) -> None:
    """Register provider listing and selection endpoints.

    :param router: Router to attach endpoints to.
    :param sessions: Session store holding the active selection.
    :param providers: Configured provider/model pairs.
    """

    @router.get("/api/providers")
    async def list_providers() -> ProviderListResponse:
        """List all configured provider/model pairs.

        :return: Provider list response.
        """
        return ProviderListResponse(
            providers=[ProviderInfo(**item) for item in providers]
        )

    @router.get("/api/providers/active")
    async def get_active_provider() -> ActiveProvider:
        """Get the currently active provider/model pair.

        :return: Active provider response.
        """
        return ActiveProvider(
            provider=sessions.active_provider, model=sessions.active_model
        )

    @router.post("/api/providers/active")
    async def set_active_provider(selection: ActiveProvider) -> ActiveProvider:
        """Switch the active provider/model pair.

        :param selection: Provider/model to activate.
        :return: The activated provider.
        """
        sessions.active_provider = selection.provider
        sessions.active_model = selection.model
        return selection
