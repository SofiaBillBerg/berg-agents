"""FastAPI web UI for the Berg Agents capability and chat layer.

This module is a thin HTTP router over the core business logic that lives
in :mod:`berg_agents.ui.chat_server` (:class:`ChatServer` singleton) and
:mod:`berg_agents.ui.orchestrator_routes`. Every route handler delegates to
the server instance:

* Unpacking Pydantic request bodies
* Wrapping server-returned dicts into response models
* Framing streaming generators with SSE (``data:`` prefix) via ``_sse``
* Translating server-side errors into ``HTTPException`` status codes

All mutable state, thread lifecycle, HITL event handling, and event queues
live in ``ChatServer``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from berg_agents.capabilities.envelope import InvokeBody
from berg_agents.config.settings import get_settings
from berg_agents.ui.chat_server import get_server
from berg_agents.ui.protocol import _sse
from berg_agents.ui.requests import (
    ActiveProviderRequest,
    ActiveProviderResponse,
    AuditListResponse,
    AuditRequest,
    AuditResponse,
    AuthMiddleware,
    CancelRequest,
    ChatRequest,
    ChatResponse,
    HistoryResponse,
    ProtocolCommand,
    ProtocolStreamRequest,
    ProviderConfig,
    ProviderListResponse,
    RequestLoggingMiddleware,
    ResumeRequest,
    SwitchModelRequest,
    ThreadCreatePayload,
)

#: Module logger - used for protocol stream error reporting.
logger = __import__("logging").getLogger(__name__)

#: Directory of the built React app (created by ``npm run build`` in webapp/).
_DIST_DIR = Path(__file__).resolve().parent / "webapp" / "dist"


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

# noinspection argument-equal-default
app = FastAPI(
    title="Berg Agents Web UI",
    description=(
        "Web interface for the berg_agents capability layer: list "
        "capabilities and invoke them through the audited registry."
    ),
    version="0.1.0",
)

if get_settings().auth_token is not None:
    app.add_middleware(AuthMiddleware)

app.add_middleware(  # type: ignore[arg-type]
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-CodeAgent-Auth-Token"],
)

app.add_middleware(RequestLoggingMiddleware)

# Include the orchestrator router before the SPA mount so `/api/*` routes are
# resolved instead of falling through to the static webapp handler.
from berg_agents.ui.orchestrator_routes import router as _orch_router

app.include_router(_orch_router)


# ---------------------------------------------------------------------------
# Route handlers - every handler delegates to LangGraphChatServer
# ---------------------------------------------------------------------------


@app.get("/providers")
async def list_providers() -> ProviderListResponse:
    """Return all configured providers and their available models."""
    server = get_server()
    raw = server.list_providers()
    return ProviderListResponse(providers=[ProviderConfig(**p) for p in raw])


@app.get("/providers/active")
async def get_active_provider() -> ActiveProviderResponse:
    """Return the currently active provider and model."""
    server = get_server()
    raw = server.get_active_provider()
    return ActiveProviderResponse(**raw)


@app.get("/api/providers")
async def api_list_providers() -> ProviderListResponse:
    return await list_providers()


@app.get("/api/providers/active")
async def api_get_active_provider() -> ActiveProviderResponse:
    return await get_active_provider()


@app.post("/api/providers/active")
async def api_set_active_provider(request: ActiveProviderRequest) -> dict[str, str]:
    return await set_active_provider(request)


@app.post("/providers/active")
async def set_active_provider(request: ActiveProviderRequest) -> dict[str, str]:
    """Switch the active provider and model, reinitializing the agent."""
    server = get_server()

    #: Validate against the configured provider list
    error = server.validate_provider(request.provider, request.model)
    if error:
        raise HTTPException(status_code=422, detail=error)

    result = await server.set_active_provider(request.provider, request.model)

    if result.get("status") == "error":
        raise HTTPException(
            status_code=503,
            detail=result.get("detail", "provider switch in progress"),
        )

    return {"status": "ok"}


@app.post("/chat/resume")
async def chat_resume(request: ResumeRequest) -> dict[str, str]:
    """Deliver an approval/reject decision for a paused HITL interrupt."""
    server = get_server()
    try:
        server.resume_hitl(request.thread_id, request.decision)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok"}


@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a chat message to the agent and return the response (legacy)."""
    server = get_server()
    result = await server.chat(request.message, request.thread_id)
    return ChatResponse(**result)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Send a chat message to the agent via SSE streaming (legacy)."""
    server = get_server()

    async def _wrap() -> AsyncGenerator[str, None]:
        try:
            async for chunk in server.chat_stream(
                request.message, request.thread_id
            ):
                yield chunk
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return StreamingResponse(
        _wrap(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Thread-Id": request.thread_id or "",
        },
    )


@app.post("/chat/cancel")
async def chat_cancel(request: CancelRequest) -> dict[str, str]:
    """Cancel a running agent thread."""
    server = get_server()
    try:
        server.cancel_legacy(request.thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "cancelled"}


@app.get("/chat/history")
async def chat_history(thread_id: str, limit: int = 20) -> HistoryResponse:
    """Return the message history for a thread."""
    server = get_server()
    messages = await server.chat_history(thread_id, limit)
    return HistoryResponse(messages=messages)


@app.post("/chat/audit")
async def chat_audit(request: AuditRequest) -> AuditResponse:
    """Record an audit log entry for a thread."""
    server = get_server()
    server.audit_entry(
        request.thread_id,
        request.action,
        request.details,
        request.timestamp,
        request.user,
    )
    return AuditResponse(status="recorded")


@app.get("/chat/audit")
async def chat_audit_list(thread_id: str) -> AuditListResponse:
    """List audit log entries for a thread."""
    server = get_server()
    entries = server.audit_list(thread_id)
    return AuditListResponse(entries=entries)


# ---------------------------------------------------------------------------
# LangGraph Protocol v2 endpoints (for useStream frontend SDK)
# ---------------------------------------------------------------------------


@app.post("/threads")
async def create_thread(payload: ThreadCreatePayload) -> dict[str, Any]:
    """Create a new thread."""
    server = get_server()
    return server.create_thread(
        payload.thread_id, payload.metadata, payload.if_exists
    )


@app.post("/threads/{thread_id}/commands")
async def thread_commands(
    thread_id: str, command: ProtocolCommand
) -> dict[str, Any]:
    """Handle a LangGraph protocol v2 command.

    Supported commands: ``run.start``, ``input.respond``, ``run.stop``.
    """
    server = get_server()
    try:
        return await server.handle_protocol_command(
            thread_id, command.method, command.params or {}, command.id or 0
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/threads/{thread_id}/stream/events")
async def thread_stream_events(
    thread_id: str,
    channels: str | None = None,
    since: int | None = None,
) -> StreamingResponse:
    """Open a LangGraph protocol v2 SSE event stream (GET with query params)."""
    server = get_server()
    _since = since or 0

    async def _event_stream() -> AsyncGenerator[str, None]:
        async for event in server.thread_stream_events(thread_id, _since):
            yield _sse(event)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/threads/{thread_id}/stream/events")
async def thread_stream_events_post(
    thread_id: str, request: ProtocolStreamRequest
) -> StreamingResponse:
    """Open a LangGraph protocol v2 SSE event stream via POST."""
    server = get_server()
    _since = request.since or 0

    async def _event_stream() -> AsyncGenerator[str, None]:
        async for event in server.thread_stream_events(thread_id, _since):
            yield _sse(event)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/threads/{thread_id}/runs/stream")
async def thread_runs_stream(
    thread_id: str,
    request: dict[str, Any],
) -> StreamingResponse:
    """Start a run and stream SSE events."""
    server = get_server()

    input_data = request.get("input", {})
    messages = input_data.get("messages", [])
    human_msg = next(
        (m for m in messages if m.get("type") in ("human", "user")), None
    )
    text = human_msg.get("content", "") if human_msg else ""

    async def _event_stream() -> AsyncGenerator[str, None]:
        if not text:
            yield _sse({
                "method": "lifecycle",
                "params": {
                    "namespace": [],
                    "data": {"event": "failed", "error": "No message content"},
                },
            })
            return

        run_id = server.start_background_run(thread_id, text)

        seq = 0
        try:
            async for event in server.thread_stream_events(thread_id, 0):
                params = event.get("params", {})
                evt_seq = params.get("seq", seq + 1)
                if evt_seq > seq:
                    seq = evt_seq
                    yield _sse(event, seq=evt_seq)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Content-Location": f"/threads/{thread_id}/runs/{uuid.uuid4()}",
        },
    )


@app.get("/threads/{thread_id}/runs/{run_id}/stream")
async def thread_runs_join_stream(
    thread_id: str,
    run_id: str,
    last_event_id: str | None = Header(None),
) -> StreamingResponse:
    """Reconnect to an existing run's SSE event stream."""
    server = get_server()
    _since = (
        int(last_event_id) if last_event_id and last_event_id != "-1" else 0
    )

    async def _event_stream() -> AsyncGenerator[str, None]:
        async for event in server.thread_stream_events(thread_id, _since):
            params = event.get("params", {})
            evt_seq = params.get("seq", _since + 1)
            if evt_seq > _since:
                _since = evt_seq
                yield _sse(event, seq=evt_seq)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/threads/{thread_id}/runs/{run_id}/cancel")
async def thread_runs_cancel(
    thread_id: str,
    run_id: str,
) -> dict[str, Any]:
    """Cancel a running task."""
    server = get_server()
    server.cancel_run(thread_id)
    return {}


@app.post("/threads/{thread_id}/history")
async def thread_history(
    thread_id: str,
    request: dict[str, Any],
) -> list[dict[str, Any]]:
    """Get past states for a thread."""
    server = get_server()
    return await server.get_thread_history(thread_id)


@app.get("/threads/{thread_id}/state")
async def thread_state(thread_id: str) -> dict[str, Any]:
    """Get the current state of a thread."""
    server = get_server()
    return await server.get_thread_state(thread_id)


@app.get("/models")
def list_models_endpoint() -> dict[str, Any]:
    """Return available models for the dynamic model selector."""
    server = get_server()
    return {"models": server.list_models()}


@app.get("/api/models")
def api_list_models_endpoint() -> dict[str, Any]:
    return list_models_endpoint()


@app.get("/threads/{thread_id}/export")
async def export_thread(thread_id: str, format: str = "md") -> Any:
    """Export a thread's conversation as a downloadable file."""
    from fastapi.responses import Response

    server = get_server()
    try:
        body = await server.export_thread(thread_id, format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Clean thread_id for filename (take first segment before dots, truncate)
    clean_id = (
        thread_id.split(".", maxsplit=1)[0][:8]
        if "." in thread_id
        else thread_id[:8]
    )
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="bergagents-chat-{clean_id}.md"'
            )
        },
    )


@app.post("/threads/{thread_id}/model")
async def switch_thread_model(
    thread_id: str, body: SwitchModelRequest
) -> dict[str, Any]:
    """Switch the model for a given thread."""
    server = get_server()
    result = await server.set_thread_model(
        thread_id, body.provider, body.model, body.base_url
    )
    if result.get("status") == "error":
        raise HTTPException(
            status_code=409, detail=result.get("detail", "Cannot switch model")
        )
    return result


@app.get("/capabilities")
def list_capabilities() -> list[dict[str, Any]]:
    """Return metadata for every registered capability."""
    server = get_server()
    return server.list_capabilities()


@app.post("/invoke")
def invoke_capability(body: InvokeBody) -> dict[str, Any]:
    """Dispatch an invocation and return the response plus audit receipt."""
    server = get_server()
    try:
        return server.invoke_capability(body.capability_id, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Static file mount - SPA at root
# ---------------------------------------------------------------------------

if _DIST_DIR.is_dir():
    from starlette.responses import FileResponse, Response

    class NoCacheStaticFiles(StaticFiles):
        """StaticFiles subclass that disables caching for SPA files."""

        async def get_response(
            self, path: str, scope: Any
        ) -> FileResponse | Response:
            response = await super().get_response(path, scope)
            if isinstance(response, FileResponse):
                response.headers["Cache-Control"] = (
                    "no-cache, no-store, must-revalidate"
                )
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response

    app.mount(
        "/",
        NoCacheStaticFiles(directory=str(_DIST_DIR), html=True),
        name="webapp",
    )

