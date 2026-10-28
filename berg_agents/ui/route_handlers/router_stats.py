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

"""Router statistics endpoint.

Extracted from ``create_router`` — one concern per module. Read-only
view over the harness Router Stats 's outcome stats.
"""

from __future__ import annotations

from typing import Any

from berg_agents.core.harness import Harness
from fastapi import APIRouter


def register_router_stats_routes(
    router: APIRouter, *, harness: Harness
) -> None:
    """Register the router/outcome statistics endpoint.

    :param router: Router to attach endpoints to.
    :param harness: Shared harness exposing the router gate.
    """

    @router.get("/api/router-stats")
    async def router_stats() -> dict[str, Any]:
        """Return router/outcome statistics.

        :return: A dictionary containing router statistics.
        """
        return harness.get_router_stats()
