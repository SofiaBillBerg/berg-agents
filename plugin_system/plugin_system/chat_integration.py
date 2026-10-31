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

"""Chat integration for the plugin system.

Loads enabled plugin tools once per server process and hands them to
the streaming chat agent (:func:`build_chat_agent`). Everything here
is failure-isolated: a broken plugin directory must never take down
the chat endpoint — it only logs and yields no tools.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING as __TYPE_CHECKING
from typing import Any

from plugin_system.lifecycle.lifecycle_states import PluginState

logger = logging.getLogger(__name__)

if __TYPE_CHECKING:
    from plugin_system.plugin_manager import PluginManager

# Checkout root of the plugin packages (this file is
# plugin_system/plugin_system/chat_integration.py → up two).
_PLUGINS_ROOT = Path(__file__).resolve().parents[2] / "berg_plugins"

# NOTE: Module-level cache — plugin discovery/loading runs once per
# process (server lifespan warms it; the chat endpoint fills it lazily
# as a fallback). Only the manager is cached: tool membership and
# descriptors are derived per call so toggles apply immediately.
# The manager holds a running event-bus task, so it must stay alive
# for the process lifetime and is never shut down here.
_CACHE: dict[str, Any] = {"manager": None}
_INIT_LOCK = asyncio.Lock()


def _plugin_search_paths() -> list[Path]:
    """Locate checkout plugin directories.

    :return: Existing directories to scan for ``plugin.yaml`` files.
    """
    # NOTE: This file lives at berg_agents/plugin_system/, so the
    # repo checkout root is two parents up.
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [repo_root / "berg_plugins"]
    return [p for p in candidates if p.is_dir()]


async def get_chat_plugin_tools() -> list[Any]:
    """Return enabled plugin tools for the chat agent.

    Runs discovery + load + enable on first call; membership is
    re-derived per call so toggles apply on the next chat turn.
    Failures are logged, never raised.

    :return: List of pydantic-ai ``Tool`` objects (possibly empty).
    """
    if _CACHE["manager"] is not None:
        return _collect_chat_tools()
    async with _INIT_LOCK:
        if _CACHE["manager"] is not None:
            return _collect_chat_tools()
        try:  # ruff: ignore[too-many-statements-in-try-clause]
            from plugin_system.plugin_manager import PluginManager

            search_paths = _plugin_search_paths()
            if not search_paths:
                return []
            # NOTE: Chat plugins run without app/harness services for
            # now — the pilot only needs tools + settings + events.
            manager = PluginManager(app=None, harness=None)
            await manager.initialize()
            await manager.discover_plugins(search_paths)
            # NOTE: Migration-guide Phase 1 — repo skills join the
            # registry as adapter plugins (same lifecycle, no rewrites).
            try:
                from plugin_system.adapters.skill_adapter import (
                    register_skill_plugins,
                )

                from berg_agents.config.settings import get_settings

                skill_settings = get_settings()
                await register_skill_plugins(manager, skill_settings.skills)
            except Exception as exc:
                logger.warning("Skill adapter registration skipped: %s", exc)
            # NOTE: Migration-guide Phase 1 — MCP servers join the
            # registry the same way (descriptor + lifecycle only;
            # toolsets keep attaching through mcp_toolsets).
            try:
                from plugin_system.adapters.mcp_adapter import (
                    register_mcp_plugins,
                )

                await register_mcp_plugins(manager)
            except Exception as exc:
                logger.warning("MCP adapter registration skipped: %s", exc)
            await manager.load_all()
            await manager.enable_all()
            # NOTE: Config kill-switch — `enabled: false` servers rest
            # disabled (user toggles can still enable them at runtime).
            try:
                from plugin_system.adapters.mcp_adapter import (
                    sync_mcp_config_states,
                )

                await sync_mcp_config_states(manager)
            except Exception as exc:
                logger.warning("MCP .berg-agents sync skipped: %s", exc)
            _CACHE["manager"] = manager
            logger.info("Plugin system warmed")
        except Exception as exc:
            # NOTE: Chat must work with zero plugins — log and move on.
            logger.warning("Plugin system unavailable for chat: %s", exc)
    return _collect_chat_tools()


def _plugin_entries() -> list[Any]:
    """Registry entries from the warmed manager (empty when down).

    :return: Plugin entries (possibly empty).
    """
    manager = _CACHE["manager"]
    if manager is None:
        return []
    try:
        return manager.registry.list_plugins()
    except Exception as exc:
        logger.warning("Plugin registry unreadable: %s", exc)
        return []


def get_plugin_manager() -> PluginManager:
    """The warm singleton manager, or raise if it was never warmed.

    Callers outside this package need the manager to run a plugin tool
    or read registry state, and reaching into ``_CACHE`` for it made
    them depend on a private name. This is the public seam for that.

    :return: The shared :class:`PluginManager`.
    :raises RuntimeError: When the manager has not been warmed yet
        (call :func:`get_chat_plugin_tools` first, which is what
        ``chat_stream`` and the tools endpoint already do).
    """
    manager = _CACHE.get("manager")
    if manager is None:
        raise RuntimeError(
            "Plugin system is not warm yet - call get_chat_plugin_tools() "
            "before touching the manager."
        )
    return manager


def _collect_chat_tools() -> list[Any]:
    """Collect tools from ENABLED plugins only.

    Membership is computed per call (not cached): toggling a plugin
    takes effect on the next chat turn without a server restart.

    :return: Pydantic-ai ``Tool`` objects from enabled plugins.
    """
    tools: list[Any] = []
    manager = _CACHE["manager"]
    if manager is None:
        return tools
    for entry in _plugin_entries():
        # NOTE: Registry keeps capabilities across disable (they are
        # the record); state decides what the model may use.
        if entry.state != PluginState.ENABLED:
            continue
        for cap in manager.registry.get_capabilities(
            plugin_id=entry.metadata.id, capability_type="tool"
        ):
            tool = getattr(cap, "tool", None)
            if tool is not None:
                tools.append(tool)
    return tools


async def get_chat_plugin_state() -> tuple[
    list[Any], frozenset[str], frozenset[str]
]:
    """Full per-turn plugin state for the chat agent.

    Ensures the cache is warm, then reports what the model may use.

    :return: ``(tools, disabled_mcp_servers, disabled_skill_ids)`` —
        enabled plugin tools, MCP server keys to exclude from toolsets,
        and chat skill ids (``skill-<name>``) to withhold.
    """
    await get_chat_plugin_tools()
    manager = _CACHE["manager"]
    disabled_mcp: set[str] = set()
    disabled_skills: set[str] = set()
    if manager is not None:
        for entry in _plugin_entries():
            if entry.state == PluginState.ENABLED:
                continue
            plugin_id = entry.metadata.id
            if plugin_id.startswith("berg-plugin-mcp-"):
                disabled_mcp.add(plugin_id.removeprefix("berg-plugin-mcp-"))
            elif plugin_id.startswith("berg-plugin-skill-"):
                # NOTE: Adapter metadata.name is the catalog name, and
                # chat skill ids are "skill-<name>" (see skills.py).
                disabled_skills.add(f"skill-{entry.metadata.name}")
    return (
        _collect_chat_tools(),
        frozenset(disabled_mcp),
        frozenset(disabled_skills),
    )


async def set_plugin_enabled(plugin_id: str, enabled: bool) -> str | None:
    """Enable or disable one plugin (powers the UI toggles).

    :param plugin_id: Plugin identifier.
    :param enabled: True to enable, False to disable.
    :return: New state string, or None for unknown plugin ids.
    """
    await get_chat_plugin_tools()
    manager = _CACHE["manager"]
    if manager is None:
        return None
    try:
        if manager.registry.get(plugin_id) is None:
            return None
        if enabled:
            await manager.enable_plugin(plugin_id)
        else:
            await manager.disable_plugin(plugin_id)
    except Exception as exc:
        logger.warning("Plugin %s toggle failed: %s", plugin_id, exc)
    entry = manager.registry.get(plugin_id)
    return str(entry.state) if entry else None


def _resolve_ui_declaration(
    plugin_id: str, plugin_path: Any, ui: Any
) -> dict[str, Any] | None:
    """Turn a manifest ``ui:`` block into a browser-loadable descriptor.

    The manifest names a *built* entry relative to the plugin package;
    the host serves ``berg_plugins/`` at ``/berg-plugins/``, so the
    descriptor's ``entry_url`` is derivable without the host importing
    anything from the plugin.

    :param plugin_id: Plugin identifier (for logging).
    :param plugin_path: Manifest path (``.../plugin.yaml``) or None.
    :param ui: Raw ``ui:`` mapping from the manifest.
    :return: Descriptor with ``entry_url`` added, or None when the
        plugin declares no UI or its entry cannot be located.
    """
    if not isinstance(ui, dict):
        return None
    entry = ui.get("entry")
    if not isinstance(entry, str) or not entry:
        return None
    descriptor = dict(ui)
    if plugin_path is None:
        return None
    package_dir = Path(plugin_path).resolve()
    built = package_dir / entry
    # NOTE: the built bundle may not exist yet (plugin never ran its
    # UI build) — still report the URL so the host can explain why
    # the surface failed to load instead of silently hiding it.
    # URL is relative to the mounted berg_plugins/ root, so it is
    # <plugin-dir>/<entry> (NOT the absolute package dir name).
    try:
        url_suffix = package_dir.relative_to(_PLUGINS_ROOT).as_posix()
    except ValueError:
        # Plugin lives outside the mounted root: fall back to the dir
        # name so the URL is still well-formed and the host can say
        # "not served" instead of crashing.
        url_suffix = package_dir.name
    descriptor["entry_url"] = f"/berg-plugins/{url_suffix}/{entry}"
    descriptor["entry_built"] = built.is_file()
    return descriptor


async def list_chat_plugins() -> list[dict[str, Any]]:
    """Describe discovered plugins for the ``/api/plugins`` endpoint.

    Descriptors rebuild per call so enable/disable toggles show up
    immediately. Never raises — returns an empty list when plugins
    are unavailable.

    :return: Plugin descriptors with id/name/version/state/tools plus
        typed ``capabilities`` (tool/skill/mcp).
    """
    await get_chat_plugin_tools()
    manager = _CACHE["manager"]
    if manager is None:
        return []
    plugins: list[dict[str, Any]] = []
    for entry in _plugin_entries():
        active = entry.state == PluginState.ENABLED
        info: dict[str, Any] = {
            "id": entry.metadata.id,
            "name": entry.metadata.name,
            "version": entry.metadata.version,
            "state": str(entry.state),
            "description": entry.metadata.description,
            "tools": [],
            "capabilities": [],
            # NOTE: the plugin's own UI declaration, resolved into a
            # browser-loadable URL from its manifest + package path.
            # The host renders whatever this describes and never
            # hardcodes a plugin's domain (or imports its source).
            "ui": _resolve_ui_declaration(
                entry.metadata.id, entry.metadata.path, entry.metadata.ui
            )}
        for cap in manager.registry.get_capabilities(
            plugin_id=entry.metadata.id
        ):
            cap_type = getattr(cap, "type", "?")
            if cap_type == "tool":
                tool = getattr(cap, "tool", None)
                if tool is None:
                    continue
                tool_name = getattr(tool, "name", "?")
                info["tools"].append(tool_name)
                info["capabilities"].append({
                    "type": "tool",
                    "id": tool_name,
                    "enabled": active})
            elif cap_type == "skill":
                skill_id = getattr(cap, "id", "?")
                info["capabilities"].append({
                    "type": "skill",
                    "id": skill_id,
                    "name": getattr(cap, "name", skill_id),
                    "enabled": active})
            elif cap_type == "mcp":
                server = getattr(cap, "id", "?")
                info["capabilities"].append({
                    "type": "mcp",
                    "id": server,
                    "name": server,
                    "server_type": getattr(cap, "server_type", ""),
                    # NOTE: Runtime state wins over the static configuration
                    # flag so toggles reflect immediately.
                    "enabled": active,
                    "sensitive": getattr(cap, "sensitive", False)})
            else:
                info["capabilities"].append({"type": cap_type})
        # NOTE: Disable unregisters capabilities, so disabled plugins
        # would go blank. Synthesize identity descriptors instead —
        # adapter metadata plus config readers, never guesses.
        if not info["capabilities"]:
            if entry.metadata.id.startswith("berg-plugin-skill-"):
                from plugin_system.adapters.skill_adapter import slugify

                info["capabilities"].append({
                    "type": "skill",
                    "id": slugify(entry.metadata.name),
                    "name": entry.metadata.name,
                    "enabled": active})
            elif entry.metadata.id.startswith("berg-plugin-mcp-"):
                from plugin_system.adapters.mcp_adapter import (
                    describe_mcp_server,
                )

                described = describe_mcp_server(
                    entry.metadata.id.removeprefix("berg-plugin-mcp-")
                )
                if described is not None:
                    # NOTE: Runtime state wins so the toggle shows.
                    described["enabled"] = active
                    info["capabilities"].append(described)
        plugins.append(info)
    return plugins
