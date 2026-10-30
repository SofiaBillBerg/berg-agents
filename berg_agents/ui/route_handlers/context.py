# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
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

"""Context endpoints.

Extracted from ``create_router`` — one concern per module. Covers the
config-driven context catalog (memory/skills/MCP) and the shared
Shared Context API that backs the in-app editor.
"""

from __future__ import annotations

import asyncio
from typing import Any

from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter, HTTPException


def register_context_routes(
    router: APIRouter, *, sessions: SessionManager
) -> None:
    """Register context catalog + shared-context endpoints.

    :param router: Router to attach endpoints to.
    :param sessions: Session store (root dir + active provider/model).
    """

    @router.get("/api/context")
    async def context_catalog() -> dict[str, Any]:
        """Catalog of everything the agent may load as context.

        Memory files (``settings.memory``), skills (parsed frontmatter
        only, no bodies), and MCP servers (names + enabled flags -
        live tool names need a running session). Mirrors the TUI
        ``/memory`` ``/skills`` ``/mcps`` listings for the web UI.

        :return: Dict with ``memory``, ``skills``, ``mcp_servers``,
            and the active provider/model.
        """
        from pathlib import Path

        from berg_agents.capabilities.mcp_toolsets import list_servers
        from berg_agents.capabilities.skills import list_skills
        from berg_agents.config.settings import get_settings

        settings = get_settings()
        # Offload the blocking resolve off the event loop (async handlers
        # should not do blocking pathlib work directly).
        root = await asyncio.to_thread(
            lambda: Path(sessions._harness_root_dir()).expanduser().resolve()
        )

        def _exists(entry: Any) -> bool:
            raw = (
                str(entry[0])
                if isinstance(entry, (list, tuple)) and entry
                else str(entry or "")
            )
            if not raw:
                return False
            candidate = Path(raw).expanduser()
            if candidate.is_absolute():
                return candidate.is_file()
            return (root / candidate).is_file()

        return {
            "memory": [
                {"path": str(m), "exists": _exists(m)}
                for m in (settings.memory or [])
            ],
            "skills": list_skills(
                settings.skills, root_dir=sessions._harness_root_dir()
            ),
            "mcp_servers": list_servers(),
            "active": {
                "provider": sessions.active_provider,
                "model": sessions.active_model}}

    @router.get("/api/context/shared")
    async def shared_context_catalog() -> dict[str, Any]:
        """Catalog of the shared context for the in-app editor.

        :return: Dict with ``scopes`` (global/project -> path), per-section
            content presence, and recent journal history.
        """
        from berg_agents.core.shared_context import SECTIONS, SharedContext

        ctx = SharedContext.resolve(sessions._harness_root_dir())
        return {
            "scopes": ctx.scopes(),
            "sections": [
                {
                    "name": name,
                    "has_content": bool(ctx.read(name).strip()),
                    "by_scope": {
                        layer.scope: bool(layer.read(name).strip())
                        for layer in ctx.layers
                    }}
                for name in SECTIONS
            ],
            "history": ctx.history()[:25]}

    @router.get("/api/context/shared/{section}")
    async def shared_context_section(section: str) -> dict[str, Any]:
        """Read one Shared Context section (project shadows global).

        :param section: Section name (an entry of ``SECTIONS``).
        :return: Effective content, scopes, and this section's history.
        :raises HTTPException: 404 for an unknown section.
        """
        from berg_agents.core.shared_context import SECTIONS, SharedContext

        if section not in SECTIONS:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown section '{section}'. Valid: {', '.join(SECTIONS)}.",
            )
        ctx = SharedContext.resolve(sessions._harness_root_dir())
        return {
            "section": section,
            "content": ctx.read(section),
            "scopes": ctx.scopes(),
            "history": ctx.history(section)[:25]}

    @router.put("/api/context/shared/{section}")
    async def shared_context_write(
        section: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        """Write/append a section from the in-app editor (author ``human:ui``).

        Sections are validated against ``SECTIONS`` so only known context
        files are writable — no arbitrary paths (workspace files ride the
        one shared file-access path, added with E2).

        :param section: Section name.
        :param body: ``content`` (required), optional ``mode``
            ("write"/"append"), ``scope`` ("project"/"global"), ``why``.
        :return: The stored result and effective content.
        :raises HTTPException: 404 unknown section, 422 bad body.
        """
        from berg_agents.core.shared_context import SECTIONS, SharedContext

        if section not in SECTIONS:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown section '{section}'. Valid: {', '.join(SECTIONS)}.",
            )
        content = body.get("content")
        if not isinstance(content, str):
            raise HTTPException(
                status_code=422, detail="Body needs a string 'content'."
            )
        mode = str(body.get("mode") or "write")
        scope = str(body.get("scope") or "project")
        why = str(body.get("why") or "")
        ctx = SharedContext.resolve(sessions._harness_root_dir())
        if mode == "append":
            changed = ctx.append(
                section, content, author="human:ui", why=why, scope=scope
            )
        else:
            changed = ctx.write(
                section, content, author="human:ui", why=why, scope=scope
            )
        return {
            "section": section,
            "changed": changed,
            "mode": mode,
            "scope": scope,
            "content": ctx.read(section)}
