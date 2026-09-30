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
    ToolExecuteRequest,
    ToolExecuteResponse,
)
from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic_ai import DeferredToolRequests
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
        # output_type adds DeferredToolRequests: tools flagged
        # requires_approval (bash, edit_file, write_file, run_task)
        # pause the run instead of executing, the adapter streams an
        # approval request, and the frontend answers it with
        # addToolApprovalResponse — which re-POSTs here carrying the
        # approval. The adapter extracts approvals from the incoming
        # messages and resumes the same run. (The adapter only adds
        # DeferredToolRequests itself when it contributes a toolset,
        # which we don't use — hence declaring it explicitly.)
        return await VercelAIAdapter.dispatch_request(
            request,
            agent=agent,
            sdk_version=6,
            output_type=[str, DeferredToolRequests],
            on_complete=None,
            on_cancel=None,
        )

    @router.get("/api/learning-stats")
    async def learning_stats() -> dict[str, Any]:
        """Return learning/outcome statistics.

        :return: A dictionary containing learning statistics.
        """
        return harness.get_learning_stats()

    @router.post("/api/tool/execute")
    async def execute_tool(request: ToolExecuteRequest) -> ToolExecuteResponse:
        """Execute one tool synchronously and return its output.

        Switches on the tool name and runs the matching
        :class:`~berg_agents.core.tool_spec.ToolSpec` (file tools)
        or the full harness pipeline (``run_task``). This is the
        endpoint the webapp's ``executeTool`` (slash commands like
        ``/read_file``) calls. Tool functions already return
        human-readable messages instead of raising, so failures
        arrive as ``status="error"`` output — never tracebacks.

        :param request: Tool name plus arguments (mapping, or a bare
            string treated as ``file_path``).
        :return: Tool name, string output, and status.
        :raises HTTPException: 404 for unknown tool names.
        """
        import asyncio

        from berg_agents.agents.factory import create_tools

        name = (request.tool or "").strip()
        args = request.args
        if isinstance(args, str):
            args = {"file_path": args} if args else {}
        if not isinstance(args, dict):
            args = {}

        if name == "run_task":
            task: dict[str, Any] = {
                "description": str(args.get("description", "")),
                "task_type": str(args.get("task_type", "generic")),
                "metadata": {}}
            if not task["description"]:
                return ToolExecuteResponse(
                    tool=name,
                    output="Missing 'description': tell me what to do, "
                    "e.g. /run_task {\"description\": \"summarize README\"}.",
                    status="error",
                )
            result = await asyncio.to_thread(
                harness.execute_task, task, task_id=f"tool-{id(task)}"
            )
            if isinstance(result, str):
                output = result
            else:
                import json as _json

                try:
                    output = _json.dumps(result, indent=2, default=str)
                except (TypeError, ValueError):
                    output = str(result)
            return ToolExecuteResponse(tool=name, output=output)

        specs = {
            spec.name: spec
            for spec in create_tools(root_dir=sessions._harness_root_dir())
        }
        spec = specs.get(name)
        if spec is None or spec.execute is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown tool '{name}'. "
                f"Available: {', '.join(sorted(specs))}, run_task.",
            )
        try:
            result = spec.execute(**args)
            if asyncio.iscoroutine(result):
                result = await result
            output = result if isinstance(result, str) else str(result)
            return ToolExecuteResponse(tool=name, output=output)
        except TypeError as exc:
            # Wrong kwargs (e.g. missing content for write_file).
            return ToolExecuteResponse(
                tool=name,
                output=f"Bad arguments for {name}: {exc}. "
                f"Send {{\"file_path\": ..., \"content\": ...}} where needed.",
                status="error",
            )
        except Exception as exc:  # Defensive: never leak tracebacks.
            logger.warning("Tool %s failed: %s", name, exc, exc_info=True)
            return ToolExecuteResponse(
                tool=name, output=f"{name} failed: {exc}", status="error"
            )

    _register_provider_routes(router, sessions, providers)
    return router
