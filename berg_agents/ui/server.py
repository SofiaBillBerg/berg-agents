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

import asyncio
from collections.abc import AsyncGenerator
import contextlib
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Any

from berg_agents.config.paths import plugins_dir
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


def _mount_plugin_assets(app: Any) -> None:
    """Serve each plugin's built UI bundle at ``/berg-plugins/<dir>/``.

    The bridge is config-driven: the manifest declares a built entry
    (``ui.entry``), the browser loads it from this URL, and the host
    never imports plugin source. Mounts the whole ``berg_plugins``
    directory so installing a plugin needs no host change.
    """
    if not plugins_dir().is_dir():
        logger.warning(
            "Plugin directory %s missing; no plugin UI assets served.",
            plugins_dir(),
        )
        return
    app.mount(
        "/berg-plugins",
        StaticFiles(directory=plugins_dir()),
        name="berg-plugins",
    )
    logger.info("Plugin UI assets mounted at /berg-plugins")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Warm the plugin tool cache, then keep the run registry swept.

    Failure-isolated: plugin errors only log, the server always starts.
    The sweeper is cancelled on shutdown, which is what releases every
    finished run's journal when the process goes down.
    """
    try:
        from plugin_system import (
            ensure_plugin_system_ready,
            get_plugin_tools_for,
        )

        await ensure_plugin_system_ready()
        # Report only: the chat role's tool count says the manager came
        # up with plugins loaded. Never raise — the server must start.
        tools = await get_plugin_tools_for("chat")
        logger.info("Plugin tools warmed: %d tools", len(tools))
        # Declarative agents (.berg-agents/agents/*.yaml) join the harness
        # registry so /api/agents lists them and /api/agents/active selects
        # them. Failure-isolated by design: a malformed spec is logged and
        # skipped, never allowed to stop the server.
        from berg_agents.agents.specs import register_spec_agents

        register_spec_agents(app.state.harness)
        # Runtime capability authoring: the chat endpoint needs the live
        # instance to inject store.load_active() into every run, so it is
        # held on app state rather than rebuilt per request.
        from berg_agents.agents.chat_agent import authored_capabilities_dir
        from pydantic_ai_harness.capability_creation import CapabilityCreation

        app.state.authored_capabilities = CapabilityCreation(
            directory=authored_capabilities_dir()
        )
    except Exception as exc:
        logger.warning("Plugin warmup skipped: %s", exc)
    # Without this task nothing ever calls prune_finished, so finished
    # runs keep their journals and their sessions keep warm agents.
    from berg_agents.ui.run_registry import SWEEP_INTERVAL_SECONDS

    registry = app.state.run_registry
    sweeper = asyncio.create_task(registry.sweep(SWEEP_INTERVAL_SECONDS))
    # The workflow queue's worker. Failure-isolated by design: if the SDK or
    # berg's broker cannot start, chat keeps working and the error is only
    # logged, exactly like the plugin warmup above.
    worker = None
    try:
        from berg_agents.workflow.registry import start_worker

        worker = start_worker()
        logger.info("Workflow queue worker started")
    except Exception as exc:
        logger.warning("Workflow queue worker not started: %s", exc)
    try:
        yield
    finally:
        sweeper.cancel()
        if worker is not None:
            worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
        if worker is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await worker


def create_app(
    harness: Harness | None = None,
    *,
    providers: list[dict[str, Any]] | None = None,
    active_provider: str | None = None,
    active_model: str | None = None,
    web_port: int = 8001,
) -> FastAPI:
    """Create the BergAgents FastAPI application.

    :param harness: Shared harness; a default one is built when
        None so the app also works standalone.
    :param providers: Provider/model pairs; resolved from settings when None.
    :param active_provider: Active provider override.
    :param active_model: Active model override.
    :param web_port: The port this app will serve on, from ``--port``. Forwarded
        to the workflow routes so the runtime's queue client points back at the
        port berg is actually on.
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
    # Sessions own their agents and runs (see berg_agents.ui.run_registry);
    # one registry for the process, next to the one harness.
    from berg_agents.ui.run_registry import RunRegistry

    app.state.run_registry = RunRegistry()
    router = create_router(
        resolved_harness,
        sessions,
        providers=resolved_providers,
        web_port=web_port,
    )
    print(
        "DEBUG create_router routes:",
        len(router.routes),
        "chat/stream:",
        any(
            getattr(r, "path", None) == "/api/chat/stream"
            for r in router.routes
        ),
    )
    app.include_router(router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    # Plugin UI assets must be mounted BEFORE the "/" catch-all below:
    # Starlette matches mounts in registration order, so a later "/"
    # would swallow /berg-plugins/* and look for it inside the webapp
    # dist (observed as a 404 for a bundle that exists on disk).
    _mount_plugin_assets(app)

    # DEPRECATED (2026-11-12) — retained intentionally, not yet removed.
    #
    # This block mounted the static export of the webapp on the API's own
    # origin. It is now inert: `next.config.mjs` removed `output: "export"` so
    # a real Next server can host the Workflow runtime (`withWorkflow`), and
    # `dist/` is a server build with no `index.html` — so the condition below is
    # false and this branch falls through to its warning.
    #
    # Sofia's instruction was explicit: keep it until the migration is complete
    # and verified, then decide whether to archive or delete. Do not remove this
    # block as leftover code — it is the fallback shape if the UI returns to
    # being served by FastAPI.
    #
    # The rest of this module is NOT deprecated: `create_app` is imported by
    # `berg_agents/app.py`, and `_mount_plugin_assets` above is still live.
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

            def _serve_page(_path: Path = page_file) -> FileResponse:
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
