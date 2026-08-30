"""FastAPI web UI for the capability layer.


NOTE, langgraphchatserver.py is to be deprecated, bergagents server is independent of langchain.
A full migration is in progress. Below text is should be removed as soon as approprite:

    This module is a **thin HTTP adapter** over the business logic that now lives
    entirely in :mod:`berg_agents.ui.langgraphchatserver` (the
    :class:`LangGraphChatServer` singleton).  Every route handler acquires the
    server via ``get_server()`` and delegates to a server method; the handler is
    responsible only for HTTP concerns:

* Unpacking Pydantic request bodies
* Wrapping server-returned dicts into response models
* Framing streaming generators with SSE (``data:`` prefix) via ``_sse``
* Translating server-side errors into ``HTTPException`` status codes

All mutable state, agent lifecycle, HITL event handling, audit logging, and
protocol-v2 event queues live in ``LangGraphChatServer`` - this file has
**zero module-level state** beyond the ``app`` object and the static mount.

Security notes:

* Every invocation is validated by the capability's own ``input_model``;
  invalid params are rejected with HTTP 400 before any tool runs.
* Requests, params and results are never logged, so secrets and API keys
  cannot leak through the web server.
* When ``BERG_AGENT_AUTH_TOKEN`` is set, every request must include a matching
  ``X-bergagents-Auth-Token`` header. Without it, the server returns HTTP 401.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from berg_agents.config.settings import get_settings

#: Module logger - used for protocol stream error reporting.
logger = __import__("logging").getLogger(__name__)

#: Directory of the built React app (created by ``npm run build`` in webapp/).
_DIST_DIR = Path(__file__).resolve().parent / "webapp" / "dist"


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------
# These are kept in web.py because they are part of the HTTP contract.  The
# SDK and the SPA depend on their shape.  When the canonical source moves to
# ``chat_schema.py`` (see ``chat_server.py``'s docstring), these will become
# thin re-imports.
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    """Configuration for a single provider/model pair.

    Attributes:
        name: Provider identifier (e.g. "ollama", "openai").
        model: Model string (e.g. "gpt-oss:20b", "gpt-4o").
    """

    name: str
    model: str


class ProviderListResponse(BaseModel):
    """Response from GET /providers.

    Attributes:
        providers: List of configured provider configurations.
    """

    providers: list[ProviderConfig]


class ActiveProviderResponse(BaseModel):
    """Response from GET /providers/active.

    Attributes:
        provider: Currently active provider name.
        model: Currently active model string.
    """

    provider: str
    model: str


class ActiveProviderRequest(BaseModel):
    """Body for POST /providers/active.

    Attributes:
        provider: Provider name to switch to.
        model: Model string to switch to.
    """

    provider: str
    model: str


class ChatMessage(BaseModel):
    """A single chat message with role and content.

    Attributes:
        role: The role of the message sender (e.g., "user", "assistant").
        content: The content of the message.
    """

    role: str
    content: str


class ChatRequest(BaseModel):
    """A request to send a chat message to the agent.

    Attributes:
        message: The user message to send.
        thread_id: Optional thread ID for conversational state.
    """

    message: str
    thread_id: str | None = None


class ChatResponse(BaseModel):
    """A response from the agent containing the reply and thread ID.

    Attributes:
        response: The assistant's response.
        thread_id: The active thread ID.
    """

    response: str
    thread_id: str


# -- SSE Event Models (kept for SDK / frontend contract) -------------------


class TokenEvent(BaseModel):
    """SSE event representing a single token chunk from the LLM."""

    type: str = "token"
    content: str


class ToolStartEvent(BaseModel):
    """SSE event emitted when a tool call begins."""

    type: str = "tool_start"
    tool: str
    input: dict[str, Any]


class ToolEndEvent(BaseModel):
    """SSE event emitted when a tool call completes."""

    type: str = "tool_end"
    tool: str
    output: str
    elapsed_s: float


class DoneEvent(BaseModel):
    """SSE event emitted when the agent completes successfully."""

    type: str = "done"


class HitlPendingEvent(BaseModel):
    """SSE event emitted when the graph pauses for human approval (HITL)."""

    type: str = "hitl_pending"
    tool: str
    input: dict[str, Any]
    thread_id: str


class ErrorEvent(BaseModel):
    """SSE event emitted when an error occurs during streaming."""

    type: str = "error"
    reason: str


class ResumeRequest(BaseModel):
    """Body for POST /chat/resume.

    Attributes:
        thread_id: The thread whose HITL interrupt is being resolved.
        decision: "approve" or "reject".
    """

    thread_id: str
    decision: Literal["approve", "reject"]


class CancelRequest(BaseModel):
    """Body for POST /chat/cancel.

    Attributes:
        thread_id: The thread whose running agent should be canceled.
    """

    thread_id: str


class HistoryRequest(BaseModel):
    """Query params for GET /chat/history.

    Attributes:
        thread_id: The thread whose history is requested.
        limit: Maximum number of messages to return (default 20).
    """

    thread_id: str
    limit: int = 20


class HistoryResponse(BaseModel):
    """Response from GET /chat/history.

    Attributes:
        messages: List of message dicts with role, content, and optional tool_calls.
    """

    messages: list[dict[str, Any]]


class AuditEntry(BaseModel):
    """A single audit log entry."""

    action: str
    details: dict[str, Any]
    timestamp: str
    user: str


class AuditRequest(BaseModel):
    """Body for POST /chat/audit.

    Attributes:
        thread_id: The thread to record the audit entry for.
        action: "approve", "reject", or "edit".
        details: Free-form dict of additional context.
        timestamp: ISO-8601 timestamp string.
        user: User identifier.
    """

    thread_id: str
    action: Literal["approve", "reject", "edit"]
    details: dict[str, Any] = {}
    timestamp: str
    user: str


class AuditResponse(BaseModel):
    """Response from POST /chat/audit."""

    status: str


class AuditListResponse(BaseModel):
    """Response from GET /chat/audit."""

    entries: list[dict[str, Any]]


class TodoEvent(BaseModel):
    """SSE event emitted when the todos list changes."""

    type: str = "todos"
    todos: list[dict[str, Any]]


class SubagentStartEvent(BaseModel):
    """SSE event emitted when a subagent starts."""

    type: str = "subagent_start"
    id: str
    name: str


class SubagentEndEvent(BaseModel):
    """SSE event emitted when a subagent ends."""

    type: str = "subagent_end"
    id: str
    name: str
    status: str = "success"


class PingEvent(BaseModel):
    """SSE heartbeat event emitted periodically to keep the connection alive."""

    type: str = "ping"


class ProtocolCommand(BaseModel):
    """A LangGraph protocol v2 command.

    Attributes:
        id: Client-generated command ID that must be echoed in the response.
        method: Command method name (e.g. "run.start", "input.respond", "run.stop").
        params: Command-specific parameters.
    """

    id: int | None = None
    method: str
    params: dict[str, Any] = {}


class ProtocolStreamRequest(BaseModel):
    """Request body for POST /threads/{thread_id}/stream/events.

    Attributes:
        channels: List of channels to subscribe to.
        namespaces: Optional list of namespace prefixes to filter.
        depth: Optional max depth for namespace matching.
        since: Optional sequence number to replay from.
    """

    channels: list[str]
    namespaces: list[list[str]] | None = None
    depth: int | None = None
    since: int | None = None


class ThreadCreatePayload(BaseModel):
    """Payload for creating a new thread.

    Attributes:
        metadata: Optional metadata to attach to the thread.
        thread_id: Optional client-generated thread ID.
        if_exists: Behavior when thread_id already exists ('raise' or 'do_nothing').
    """

    metadata: dict[str, Any] | None = None
    thread_id: str | None = None
    if_exists: str | None = None


class SwitchModelRequest(BaseModel):
    """Body for switching a thread's model.

    Attributes:
        provider: The provider name (e.g. "openai", "ollama").
        model: The model name (e.g. "gpt-4", "mistral").
        base_url: Optional base URL for the provider (if not default).
    """

    provider: str
    model: str
    base_url: str | None = None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuthMiddleware:
    """Reject requests that lack a valid auth token when one is configured.

    The expected token is read from the ``BERG_AGENT_AUTH_TOKEN`` environment
    variable and compared against the ``X-CodeAgent-Auth-Token`` header.
    This provides a simple way to password-protect the web API when exposed
    to untrusted networks.
    When no ``BERG_AGENT_AUTH_TOKEN`` is set, the middleware allows all requests.

    Attributes:
        app: The wrapped ASGI application.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode().lower(): v.decode() for k, v in scope.get("headers", [])
        }
        token = headers.get("x-bergagents-auth-token")
        expected = get_settings().auth_token

        if expected is not None and token != expected:
            from fastapi.responses import JSONResponse

            response = JSONResponse(
                content={"detail": "Unauthorized"}, status_code=401
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


class RequestLoggingMiddleware:
    """Log all incoming requests for debugging."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            method = scope.get("method", "?")
            path = scope.get("path", "?")
            query = scope.get("query_string", b"").decode(
                "utf-8", errors="replace"
            )
            print(f"[REQ] {method} {path}?{query}")
        await self.app(scope, receive, send)
