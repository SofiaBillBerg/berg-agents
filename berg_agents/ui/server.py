"""FastAPI application factory for berg_agents.

Builds the web application around one injected harness: routes in
:mod:`berg_agents.ui.routes`, session state in
:mod:`berg_agents.ui.sessions`, schemas in :mod:`berg_agents.ui.schemas`.
"""

#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from berg_agents.config.settings import get_settings
from berg_agents.core.harness import Harness
from berg_agents.ui.routes import create_router
from berg_agents.ui.sessions import SessionManager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Static export of the Next.js webapp: ``bun run next build`` writes
# ``berg_agents/ui/webapp/dist/`` (see ``next.config.mjs`` distDir).
_WEB_DIST = Path(__file__).resolve().parent / "webapp" / "dist"


def create_app(
    harness: Harness | None = None,
    *,
    providers: list[dict[str, Any]] | None = None,
    active_provider: str | None = None,
    active_model: str | None = None,
) -> FastAPI:
    """Create the BergAgents FastAPI application.

    :param harness: Shared harness; a default one is built when
        None so the app also works standalone.
    :param providers: Provider/model pairs; resolved from settings when None.
    :param active_provider: Active provider override.
    :param active_model: Active model override.
    :return: Configured FastAPI application.
    """
    settings = get_settings()
    resolved_harness = harness or Harness(enable_inference=True)
    resolved_provider = active_provider or settings.provider or "ollama"
    # Default model: the configured default wins when it names a
    # declared model (it may live under a different provider block,
    # in which case the provider follows the model); otherwise the
    # first model under the active provider is used.
    if active_model is not None:
        resolved_model = active_model
    elif settings.default_model:
        try:
            from berg_agents.providers.registry import (
                resolve_model as _resolve_model,
            )

            resolved = _resolve_model(settings.default_model)
            resolved_provider = resolved["_provider"]
            resolved_model = resolved["model"]
        except KeyError:
            logger.warning(
                "default_model %r is not declared in 'providers'; "
                "falling back to the first model under %r",
                settings.default_model,
                resolved_provider,
            )
            block = (settings.providers or {}).get(resolved_provider) or {}
            models = block.get("models") or {}
            resolved_model = next(iter(models)) if models else ""
    else:
        block = (settings.providers or {}).get(resolved_provider) or {}
        models = block.get("models") or {}
        resolved_model = next(iter(models)) if models else ""
    # Provider list: explicit override wins, else every registry pair.
    if providers is not None:
        resolved_providers = providers
    elif settings.provider_list:
        resolved_providers = [
            {"name": item.get("name", ""), "model": item.get("model", "")}
            for item in settings.provider_list
        ]
    else:
        from berg_agents.providers.registry import list_models

        pairs = list_models(settings.model_dump())
        resolved_providers = (
            [{"name": m["provider"], "model": m["model"]} for m in pairs]
            if pairs
            else [{"name": resolved_provider, "model": resolved_model}]
        )
    sessions = SessionManager(
        active_provider=resolved_provider,
        active_model=resolved_model,
        root_dir=settings.root_dir,
    )

    app = FastAPI(title="BergAgents")
    # Local dev CORS: `next dev` (any localhost port) talks to this
    # backend directly when NEXT_PUBLIC_API_BASE_URL is set.
    # Production serves the static export same-origin, so this is
    # a no-op there.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.harness = resolved_harness
    app.state.sessions = sessions
    app.include_router(
        create_router(resolved_harness, sessions, providers=resolved_providers)
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    if _WEB_DIST.joinpath("index.html").is_file():
        # Production UI on the same origin (single :8001).
        # Mounted after the API router so /api/* always wins.
        #
        # The static export writes sub-routes as top-level "<route>.html"
        # files (e.g. dist/agents.html), which Starlette's StaticFiles
        # will NOT resolve for "/agents" (it only serves index.html inside
        # a matching directory). Explicit routes cover them, with HEAD
        # declared alongside GET.
        for route_page in ("agents", "context"):
            page_file = _WEB_DIST / f"{route_page}.html"
            if page_file.is_file():

                def _serve_page(
                    _path: Path = page_file,
                ) -> FileResponse:
                    return FileResponse(_path, media_type="text/html")

                app.api_route(
                    f"/{route_page}",
                    methods=["GET", "HEAD"],
                    name=f"webapp-{route_page}",
                    include_in_schema=False,
                )(_serve_page)
        app.mount(
            "/", StaticFiles(directory=_WEB_DIST, html=True), name="webapp"
        )
    else:
        logger.warning(
            "Web UI not built (%s missing); API only. Run "
            "'bun run next build' in berg_agents/ui/webapp/.",
            _WEB_DIST / "index.html",
        )

    return app
