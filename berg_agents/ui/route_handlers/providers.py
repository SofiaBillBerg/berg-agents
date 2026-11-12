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
        """List all configured provider/model pairs, as of THIS request.

        Resolved per request rather than from the list ``create_app`` built at
        startup: a config edit (adding a model, renaming a tag) used to be
        invisible until the server restarted, which read as "berg ignores my
        config" when it had only read it once. Sofia hit this on 2026-11-12 —
        the webapp kept showing a stale ``:12b`` tag after the config moved to
        ``:latest``, and only a restart fixed it, which is not a reasonable
        answer to "why is my new model not in the list".

        The active pair stays on the session (that IS state), but the catalog
        is configuration, so it is read fresh.

        :return: Provider list response.
        """
        from berg_agents.config.settings import Settings
        from berg_agents.providers.registry import list_models

        # ``Settings()``, not ``get_settings()``: get_settings is @lru_cache, so
        # it would hand back the SAME object forever and this endpoint would
        # still answer from the boot-time read. Constructing fresh is what makes
        # the edit visible without a restart.
        settings = Settings()
        # An explicit ``provider_list`` override still wins, exactly as
        # ``create_app`` resolves it — one rule, not two.
        if settings.provider_list:
            pairs = [
                # `name`, not `provider`: ProviderInfo's field is `name`.
                {"name": item.get("name", ""), "model": item.get("model", "")}
                for item in settings.provider_list
            ]
        else:
            # list_models reports `provider`, so it is mapped to `name` here —
            # the same mapping create_app does, so one rule not two.
            pairs = [
                {"name": m["provider"], "model": m["model"]}
                for m in list_models(settings.model_dump())
            ]

        return ProviderListResponse(
            providers=[ProviderInfo(**item) for item in pairs]
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
