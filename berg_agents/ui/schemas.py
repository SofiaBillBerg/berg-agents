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


class ModelTier(BaseModel):
    """One routing tier and the models it offers, best first."""

    name: str
    models: list[str]


class TierListResponse(BaseModel):
    """Response from GET /api/tiers."""

    tiers: list[ModelTier]


class ActiveProvider(BaseModel):
    """Currently active provider/model pair."""

    provider: str
    model: str


class DelegateModel(BaseModel):
    """The model delegated sub-agents run on."""

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


class SessionCompactRequest(BaseModel):
    """Request to compact one session's history (the /compact command).

    ``focus`` is optional: the model decides what still matters, and the
    user's instruction steers that judgement when given.
    """

    focus: str | None = None


class SessionCreateRequest(BaseModel):
    """Request to create a server-side chat session."""

    title: str | None = None


class SessionRenameRequest(BaseModel):
    """Request to rename a session (explicit user title)."""

    title: str
