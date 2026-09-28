"""Pydantic schemas for the berg_agents web API.

Single source of truth for the HTTP contract between the FastAPI backend
(:mod:`berg_agents.ui.routes`) and the Next.js frontend (``ui/webapp``).
Every model here is used by at least one endpoint — no unused models.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HarnessRequest(BaseModel):
    """Request to execute a task through the harness."""

    description: str = Field(min_length=1)
    task_type: str = "generic"
    metadata: dict[str, Any] | None = None
    model: str | None = None


class HitlDecision(BaseModel):
    """Human decision for a thread awaiting review."""

    decision: Literal["approve", "reject", "edit"]
    edited_action: dict[str, Any] | None = None


class ThreadResponse(BaseModel):
    """A thread identifier returned by thread endpoints."""

    thread_id: str


class ThreadStatusResponse(ThreadResponse):
    """Thread identifier plus its current status."""

    status: str


class HitlAckResponse(ThreadResponse):
    """Acknowledgement of a recorded HITL decision."""

    status: str
    decision: str


class ProviderInfo(BaseModel):
    """One provider/model pair."""

    name: str
    model: str


class ProviderListResponse(BaseModel):
    """Response from GET /api/providers."""

    providers: list[ProviderInfo]


class ActiveProvider(BaseModel):
    """Currently active provider/model pair."""

    provider: str
    model: str


class ChatRequest(BaseModel):
    """Simple chat request — no task pipeline, just LLM conversation."""

    message: str = Field(min_length=1)
    model: str | None = None
