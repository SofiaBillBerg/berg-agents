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

"""Plugin endpoints.

Extracted from ``create_router`` — one concern per module. Covers
plugin discovery, generic tool execution, and enable/disable toggles.
The ``_run_plugin_tool`` helper lives here too (its only caller is
``run_plugin_tool``); it is NOT imported back from ``routes.py`` —
that would be circular.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from berg_agents.ui.sessions import SessionManager
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)


async def _run_plugin_tool(
    plugin_id: str,
    tool_name: str,
    args: dict[str, Any],
    root_dir: str,
    session_id: str | None = None,
) -> Any:
    """Run a loaded plugin's tool by name (no todo/shared-todo naming).

    The dispatch resolves the live plugin instance from the warmed
    plugin manager, finds the named tool among the capabilities it
    registered, and calls its underlying function. This is the single
    path plugin UIs use — the host knows only tool names, never the
    plugin's domain.

    A plugin that declares ``session_scope`` has that argument bound per
    session by :func:`plugin_system.get_plugin_tools_for`, so the call is
    made through the role's *bound* tools: the UI reads and writes the
    same store the chat agent does. Calling the raw registered function
    instead would use the manifest default and silently show the user a
    different list than the model is working on.

    :param plugin_id: Plugin identifier.
    :param tool_name: Tool name as declared by the plugin.
    :param args: Keyword arguments for the tool.
    :param root_dir: Project root (plugin config / storage base).
    :param session_id: Session whose scoped store the UI is looking at.
    :return: The tool's return value (usually a string).
    :raises KeyError: When the plugin or tool is unknown.
    """
    from plugin_system import ensure_plugin_system_ready, get_plugin_manager
    from plugin_system.lifecycle.lifecycle_states import PluginState

    # Ensure the manager is warm (idempotent, cheap after first call).
    await ensure_plugin_system_ready()
    try:
        manager = get_plugin_manager()
    except RuntimeError as exc:
        raise KeyError(f"Plugin system unavailable: {exc}") from None
    entry = manager.registry.get(plugin_id)
    if entry is None or entry.state == PluginState.DISCOVERED:
        raise KeyError(f"Unknown plugin: {plugin_id}")
    if entry.state != PluginState.ENABLED:
        raise KeyError(f"Plugin {plugin_id} is not enabled")

    def _matches(tool: Any) -> bool:
        # Names come from the Tool's `name`, but fall back to the
        # wrapped function's __name__ so server-side helpers (which
        # are not model-facing tools) stay callable too.
        candidates = {
            str(getattr(tool, "name", "") or ""),
            str(getattr(getattr(tool, "function", None), "__name__", "") or "")}
        return tool_name in candidates

    # Preferred: the session-bound tool the model also uses. The roles
    # come from THIS plugin's manifest (falling back to the chat role,
    # which is what an undeclared plugin means), so the host never bakes
    # in a role list that a manifest could disagree with.
    from plugin_system import get_plugin_tools_for

    roles = tuple(getattr(entry.metadata, "toolset_roles", ()) or ("chat",))
    for role in roles:
        for tool in await get_plugin_tools_for(
            role, root_dir=root_dir, session_id=session_id
        ):
            if _matches(tool):
                return getattr(tool, "function", tool)(**args)

    # Fallback: a server-side helper no agent role is granted. It has no
    # bound store, so it runs with the plugin's own defaults.
    for cap in manager.registry.get_capabilities(
        plugin_id=plugin_id, capability_type="tool"
    ):
        tool = getattr(cap, "tool", None)
        if tool is None or not _matches(tool):
            continue
        function = getattr(tool, "function", tool)
        return function(**args)
    raise KeyError(f"Unknown tool {tool_name} on plugin {plugin_id}")


def register_plugin_routes(
    router: APIRouter, *, sessions: SessionManager
) -> None:
    """Register plugin discovery, tool execution, and toggles.

    :param router: Router to attach endpoints to.
    :param sessions: Session store (root dir for plugin tool defaults).
    """

    @router.get("/api/plugins")
    async def list_plugins() -> dict[str, Any]:
        """List discovered plugins and their chat tools.

        Powers the web UI plugin surfaces (side-panel/canvas): the
        frontend matches tool calls against these names to decide
        when to render a plugin view instead of a generic tool card.

        :return: Dict with ``plugins`` descriptors.
        """
        from plugin_system import list_chat_plugins

        return {"plugins": await list_chat_plugins()}

    @router.post("/api/plugins/{plugin_id}/tools/{tool_name}")
    async def run_plugin_tool(
        plugin_id: str, tool_name: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Run a loaded plugin's tool by name (generic, plugin-agnostic).

        Plugin UIs call this instead of any todo-specific endpoint: the
        plugin's own callable runs with the project's `.berg-agents` in
        scope, so the tool's `todo_path`-style defaults resolve to the
        plugin's configured store.

        :param plugin_id: Plugin identifier.
        :param tool_name: Tool name the plugin declares.
        :param body: Keyword arguments for the tool.
        :return: Dict with ``result`` (string) or ``error``.
        :raises HTTPException: 404 for unknown plugin/tool, 502 when the
            tool raises.
        """
        args = {
            k: v
            for k, v in (body or {}).items()
            if k not in {"sessionId", "tool", "args"}
        }
        root_dir = sessions._harness_root_dir()
        # The UI names the session it is displaying; the tool then runs
        # against that session's scoped store — the same one the chat
        # agent writes — instead of a process-global cwd or a manifest
        # default every session would share.
        session_id = str((body or {}).get("sessionId") or "") or None
        try:
            result = await _run_plugin_tool(
                plugin_id, tool_name, args, root_dir, session_id=session_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning(
                "Plugin tool %s/%s failed: %s", plugin_id, tool_name, exc
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        # Tools return human-readable strings for the model; a UI wants
        # structured data, so non-string returns are passed through as
        # JSON the caller can parse.
        if isinstance(result, str):
            return {"plugin": plugin_id, "tool": tool_name, "result": result}
        try:
            encoded = json.dumps(result, default=str)
        except (TypeError, ValueError):
            encoded = json.dumps({"value": str(result)})
        return {"plugin": plugin_id, "tool": tool_name, "result": encoded}

    @router.post("/api/plugins/{plugin_id}/enable")
    async def enable_plugin_endpoint(plugin_id: str) -> dict[str, Any]:
        """Enable a plugin (its tools rejoin the chat agent).

        :param plugin_id: Plugin identifier.
        :return: Dict with the plugin ``id`` and new ``state``.
        :raises HTTPException: 404 for unknown plugin ids.
        """
        from plugin_system import set_plugin_enabled

        state = await set_plugin_enabled(plugin_id, enabled=True)
        if state is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown plugin '{plugin_id}'."
            )
        return {"id": plugin_id, "state": state}

    @router.post("/api/plugins/{plugin_id}/disable")
    async def disable_plugin_endpoint(plugin_id: str) -> dict[str, Any]:
        """Disable a plugin (its tools leave the chat agent).

        MCP servers stop attaching toolsets, todo tools stop being
        offered, and skills stop loading — all from the next chat turn.

        :param plugin_id: Plugin identifier.
        :return: Dict with the plugin ``id`` and new ``state``.
        :raises HTTPException: 404 for unknown plugin ids.
        """
        from plugin_system import set_plugin_enabled

        state = await set_plugin_enabled(plugin_id, enabled=False)
        if state is None:
            raise HTTPException(
                status_code=404, detail=f"Unknown plugin '{plugin_id}'."
            )
        return {"id": plugin_id, "state": state}
