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


class TodoSubtask(BaseModel):
    """One subtask checklist item within a shared-todo item."""

    index: int
    text: str
    done: bool = False


class TodoItem(BaseModel):
    """One shared-todo item for the plugin UI surface."""

    id: str
    title: str
    status: str
    description: str = ""
    subtasks: list[TodoSubtask] = []
    file: str


class TodoCreateRequest(BaseModel):
    """Request to create a shared-todo item."""

    title: str
    description: str = ""


class SubtaskCreateRequest(BaseModel):
    """Request to append a subtask to a shared-todo item."""

    text: str


class SubtaskUpdateRequest(BaseModel):
    """Request to check or uncheck a subtask."""

    done: bool = True


class TodoUpdateRequest(BaseModel):
    """Request to update a shared-todo item (any subset of fields)."""

    title: str | None = None
    description: str | None = None
    status: str | None = None


class SessionCreateRequest(BaseModel):
    """Request to create a server-side chat session."""

    title: str | None = None


class SessionRenameRequest(BaseModel):
    """Request to rename a session (explicit user title)."""

    title: str
