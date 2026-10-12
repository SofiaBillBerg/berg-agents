"""Pydantic schemas for the berg_agents web API.

Single source of truth for the HTTP contract between the FastAPI backend
(:mod:`berg_agents.ui.routes`) and the Next.js frontend (``ui/webapp``).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


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


class ToolExecuteRequest(BaseModel):
    """Request to execute one tool synchronously.

    Matches what the webapp's ``executeTool`` sends: ``{tool, args}``.
    ``args`` is normally a mapping (``{"file_path": ...}``), but a
    bare string is accepted for single-argument tools and treated
    as ``file_path``.
    """

    tool: str
    args: dict[str, Any] | str | None = None


class ToolExecuteResponse(BaseModel):
    """Result of a synchronous tool execution."""

    tool: str
    output: str
    status: str = "ok"
