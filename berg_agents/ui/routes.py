"""HTTP endpoints for the berg_agents web API.

All routes consumed by the Next.js frontend (``webapp/app``).
The streaming chat endpoint uses :class:`~pydantic_ai.ui.vercel_ai.VercelAIAdapter`
for native Vercel AI SSE protocol — no manual event-loop / SSE translation needed.
"""

from __future__ import annotations

import logging
from typing import Any

from berg_agents.core.harness import Harness
from berg_agents.ui.schemas import (
    ActiveProvider,
    ProviderInfo,
    ProviderListResponse,
)
from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

logger = logging.getLogger(__name__)


def _register_provider_routes(
    router: APIRouter,
    sessions: SessionManager,
    providers: list[dict[str, Any]],
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
        :return: The activated provider/model.
        """
        sessions.active_provider = selection.provider
        sessions.active_model = selection.model
        return selection


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

    @router.get("/api/agents")
    async def list_agents() -> list[dict[str, Any]]:
        """List all registered agents.

        :return: A list of dictionaries containing information about each agent.
        """
        return harness.get_agent_info()

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

    @router.post("/api/chat/stream")
    async def chat_stream(
        request: Request,
    ) -> Response:
        """Agentic streaming chat — native Vercel AI protocol via pydantic_ai.

        Uses :class:`~pydantic_ai.ui.vercel_ai.VercelAIAdapter` to handle all
        event transformation: frontend messages → agent run input, agent
        events → Vercel AI SSE chunks (text deltas, tool calls, tool results,
        HITL approval requests).

        Simple messages like "hello" get a direct LLM reply — no tool calls.
        Complex requests (e.g. "write a file") trigger the model's tools
        (file operations + ``run_task``), which run the full BergAgents pipeline.

        The agent, model, and system prompt all come from configuration
        (``config/bergagents.jsonc`` and ``config/profiles.yaml``) — never
        hardcoded. An optional ``?model=`` query param overrides the model.

        :param request: FastAPI request — VercelAIAdapter inspects the body
            and ``accept`` header to pick the protocol and parse messages.
        :return: StreamingResponse with SSE chunks in Vercel AI protocol.
        """
        from berg_agents.agents.chat_agent import build_chat_agent

        # Model override via query param (the body is consumed by the adapter).
        model_id = (
            request.query_params.get("model") or sessions.active_model or ""
        )
        agent = build_chat_agent(
            model_id, root_dir=sessions._harness_root_dir()
        )

        # sdk_version=6 enables tool-approval streaming (human-in-the-loop).
        # VercelAIAdapter.dispatch_request handles all SSE encoding and
        # protocol transformation natively — no manual event loops needed.
        return await VercelAIAdapter.dispatch_request(
            request,
            agent=agent,
            sdk_version=6,
            on_complete=None,
            on_cancel=None,
        )

    @router.get("/api/learning-stats")
    async def learning_stats() -> dict[str, Any]:
        """Return learning/outcome statistics.

        :return: A dictionary containing learning statistics.
        """
        return harness.get_learning_stats()

    _register_provider_routes(router, sessions, providers)
    return router
