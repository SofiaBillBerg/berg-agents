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

"""FastAPI application factory for berg_agents.

Builds the web application around one injected harness: routes in
:mod:`berg_agents.ui.routes`, session state in
:mod:`berg_agents.ui.sessions`, schemas in :mod:`berg_agents.ui.schemas`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
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

# Plugin packages live at the checkout root: this file is
# berg_agents/ui/server.py, so root is three parents up.
_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "berg_plugins"


def _mount_plugin_assets(app: Any) -> None:
    """Serve each plugin's built UI bundle at ``/berg-plugins/<dir>/``.

    The bridge is config-driven: the manifest declares a built entry
    (``ui.entry``), the browser loads it from this URL, and the host
    never imports plugin source. Mounts the whole ``berg_plugins``
    directory so installing a plugin needs no host change.
    """
    if not _PLUGINS_DIR.is_dir():
        logger.warning(
            "Plugin directory %s missing; no plugin UI assets served.",
            _PLUGINS_DIR,
        )
        return
    app.mount(
        "/berg-plugins",
        StaticFiles(directory=_PLUGINS_DIR),
        name="berg-plugins",
    )
    logger.info("Plugin UI assets mounted at /berg-plugins")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Warm the plugin tool cache at server startup.

    Failure-isolated: plugin errors only log, the server always starts.
    """
    try:
        from berg_agents.plugin_system.chat_integration import (
            get_chat_plugin_tools,
        )

        tools = await get_chat_plugin_tools()
        logger.info("Plugin tools warmed: %d tools", len(tools))
    except Exception as exc:
        logger.warning("Plugin warmup skipped: %s", exc)
    yield


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

    app = FastAPI(title="BergAgents", lifespan=_lifespan)

    @app.middleware("http")
    async def _no_cache_documents(request: Any, call_next: Any) -> Any:
        """Keep browsers from running stale frontend vintages.

        HTML documents are entry points (they reference hashed JS/CSS),
        so they must revalidate every load; the hashed assets under
        /_next/static stay long-cached. Without this, one tab can run
        last week's App next to a fresh page (observed: old chat UI
        beside the new history page on the same origin).
        """
        response = await call_next(request)
        if not request.url.path.startswith("/api"):
            content_type = response.headers.get("content-type", "")
            # HTML entry points revalidate every load (they reference
            # hashed JS/CSS). Plugin UI bundles get the same treatment
            # for a different reason: their URL never changes, but the
            # plugin can rebuild the bundle at any time, so a cached
            # copy silently hides plugin work (observed: stale
            # subtask UI served after a rebuild). revalidate, not
            # no-store - the etag still makes this cheap.
            if "text/html" in content_type or request.url.path.startswith(
                "/berg-plugins/"
            ):
                response.headers["Cache-Control"] = "no-cache"
        return response

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

    # Plugin UI assets must be mounted BEFORE the "/" catch-all below:
    # Starlette matches mounts in registration order, so a later "/"
    # would swallow /berg-plugins/* and look for it inside the webapp
    # dist (observed as a 404 for a bundle that exists on disk).
    _mount_plugin_assets(app)

    if _WEB_DIST.joinpath("index.html").is_file():
        # Production UI on the same origin (single :8001).
        # Mounted after the API router so /api/* always wins.
        #
        # The static export writes each route as a "<route>.html" file
        # (e.g. dist/agents.html, and nested ones like
        # dist/dev/plugins.html). Starlette's StaticFiles only serves a
        # directory's index.html, so a clean "/agents" or nested
        # "/dev/plugins" would 404 without an explicit route. Discover
        # every exported page from disk and register it (GET + HEAD), so
        # adding a route — nested or not — needs no server edit.
        for page_file in sorted(_WEB_DIST.rglob("*.html")):
            rel = page_file.relative_to(_WEB_DIST)
            route_path = "/" + rel.with_suffix("").as_posix()
            # "/" plus Next's framework internals stay with StaticFiles.
            if route_path in {"/index", "/404", "/_not-found"}:
                continue

            def _serve_page(
                _path: Path = page_file,
            ) -> FileResponse:
                return FileResponse(_path, media_type="text/html")

            app.api_route(
                route_path,
                methods=["GET", "HEAD"],
                name="webapp" + route_path.replace("/", "-"),
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
