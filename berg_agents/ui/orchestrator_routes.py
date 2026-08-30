"""FastAPI routes for the orchestrator-based web server.

This module provides HTTP endpoints for the new multi-agent system:
- GET /api/agents - list all registered agents
- POST /api/orchestrate - submit a task for execution
- GET /api/orchestrate/{thread_id}/stream - SSE stream of events
- POST /api/orchestrate/{thread_id}/respond - respond to HITL interrupt
- GET /api/learning-stats - outcome statistics
"""

from __future__ import annotations

import logging
from logging import Logger
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from berg_agents.ui.orchestrator_server import get_orchestrator_server

logger: Logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class OrchestrateRequest(BaseModel):
    """Request to execute a task through the orchestrator."""

    description: str
    task_type: str = "generic"
    metadata: dict[str, Any] | None = None


class HitlResponse(BaseModel):
    """Response to a HITL interrupt."""

    decision: str  # "approve" or "reject"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/api/agents")
async def list_agents() -> list[dict[str, Any]]:
    """List all registered agents with their info."""
    server = get_orchestrator_server()
    return server.list_agents()


@router.get("/api/agents/{name}")
async def get_agent(name: str) -> dict[str, Any]:
    """Get info for a specific agent."""
    server = get_orchestrator_server()
    try:
        return server.get_agent(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


@router.post("/api/orchestrate")
async def orchestrate(request: OrchestrateRequest) -> dict[str, Any]:
    """Execute a task through the orchestrator (synchronous)."""
    server = get_orchestrator_server()
    result = await server.execute_task(
        description=request.description,
        task_type=request.task_type,
        metadata=request.metadata,
    )
    return result


@router.post("/api/orchestrate/{thread_id}/stream")
async def submit_task_stream(
    thread_id: str,
    request: OrchestrateRequest,
) -> dict[str, str]:
    """Submit a task for background execution with SSE streaming."""
    server = get_orchestrator_server()
    await server.submit_task_stream(
        description=request.description,
        task_type=request.task_type,
        thread_id=thread_id,
        metadata=request.metadata,
    )
    return {"thread_id": thread_id, "status": "started"}


@router.get("/api/orchestrate/{thread_id}/events")
async def stream_events(thread_id: str):
    """Stream orchestrator events for a thread via SSE."""
    server = get_orchestrator_server()

    async def event_generator():
        async for event in server.stream_events(thread_id):
            yield f"data: {event}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.post("/api/orchestrate/{thread_id}/respond")
async def respond_to_hitl(
    thread_id: str, response: HitlResponse
) -> dict[str, Any]:
    """Respond to a HITL interrupt."""
    server = get_orchestrator_server()
    result = await server.respond_to_hitl(thread_id, response.decision)
    return result


@router.get("/api/learning-stats")
async def get_learning_stats() -> dict[str, Any]:
    """Get learning/outcome statistics."""
    server = get_orchestrator_server()
    return server.get_learning_stats()


@router.post("/api/threads")
async def create_thread() -> dict[str, str]:
    """Create a new thread ID."""
    server = get_orchestrator_server()
    thread_id = server.create_thread()
    return {"thread_id": thread_id}


@router.post("/api/threads/{thread_id}/cancel")
async def cancel_task(thread_id: str) -> dict[str, str]:
    """Cancel a running task."""
    server = get_orchestrator_server()
    server.cancel_task(thread_id)
    return {"status": "cancelled"}
