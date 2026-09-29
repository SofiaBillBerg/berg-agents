"""Pydantic schemas for the berg_agents web API.

Single source of truth for the HTTP contract between the FastAPI backend
(:mod:`berg_agents.ui.routes`) and the Next.js frontend (``ui/webapp``).
"""

from __future__ import annotations

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
