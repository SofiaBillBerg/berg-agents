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
the streaming chat agent (:func:`berg_agents.agents.chat_agent.build_chat_agent`). Everything here
is failure-isolated: a broken plugin directory must never take down
the chat endpoint — it only logs and yields no tools.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING as __TYPE_CHECKING
from typing import Any

from plugin_system.lifecycle.lifecycle_states import PluginState

logger = logging.getLogger(__name__)

if __TYPE_CHECKING:
    from plugin_system.plugin_manager import PluginManager

#: Role used when a caller does not say which agent it is. Declared here,
#: above every use, because the collectors below default to it.
DEFAULT_AGENT_ROLE = "chat"

# NOTE: Module-level cache — plugin discovery/loading runs once per
# process (server lifespan warms it; the chat endpoint fills it lazily
# as a fallback). Only the manager is cached: tool membership and
# descriptors are derived per call so toggles apply immediately.
# The manager holds a running event-bus task, so it must stay alive
# for the process lifetime and is never shut down here.
_CACHE: dict[str, Any] = {"manager": None}
_INIT_LOCK = asyncio.Lock()


def _plugin_search_paths() -> list[Path]:
    """Locate the plugin directory to scan for ``plugin.yaml`` files.

    The location belongs to the host, not to this library: an installed
    plugin_system has no checkout around it, so the path comes from
    :func:`berg_agents.config.paths.plugins_dir` when the host is
    importable, and from ``BERG_AGENT_PLUGINS_DIR`` otherwise.

    :return: Existing directories to scan for ``plugin.yaml`` files.
    """
    try:
        from berg_agents.config.paths import plugins_dir
    except ImportError:  # standalone plugin_system, no host package
        plugins_dir = None
    if plugins_dir is not None:
        candidates = [plugins_dir()]
    else:
        override = os.environ.get("BERG_AGENT_PLUGINS_DIR")
        if not override:
            return []
        candidates = [Path(override).expanduser()]
    return [p for p in candidates if p.is_dir()]


async def ensure_plugin_system_ready() -> None:
    """Warm the plugin manager (discovery + load + enable), once.

    This is the warm-up seam: callers that need the registry (the tools
    endpoint) or a startup count (the server lifespan) call it and then
    read the manager. Agent tool lists do NOT come from here — they come
    from :func:`get_plugin_tools_for`, which applies the role rule and
    the session binding. Warming and tool-membership are separate
    concerns, and keeping them apart is what stops a role-less second
    membership rule from reappearing.

    Idempotent after the first call. Failures are logged, never raised:
    chat must work with zero plugins.
    """
    if _CACHE["manager"] is not None:
        return
    async with _INIT_LOCK:
        if _CACHE["manager"] is not None:
            return
        try:  # ruff: ignore[too-many-statements-in-try-clause]
            from plugin_system.plugin_manager import PluginManager

            search_paths = _plugin_search_paths()
            if not search_paths:
                return
            # NOTE: Chat plugins run without app/harness services for
            # now — the pilot only needs tools + settings + events.
            manager = PluginManager(app=None, harness=None)
            await manager.initialize()
            # ``list`` is invariant, so the concrete Path list is widened
            # to the parameter's declared element type explicitly.
            await manager.discover_plugins(list[Path | str](search_paths))
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


async def get_plugin_tools_for(
    agent_role: str = DEFAULT_AGENT_ROLE,
    *,
    root_dir: str | Path | None = None,
    session_id: str | None = None,
) -> list[Any]:
    """Tools an agent role may use, bound to this session's storage.

    This is the one entry point every agent uses — the chat agent, and
    the planner/implementer subagents it delegates to. Two rules decide
    what comes back:

    * the plugin's manifest must grant *agent_role* (see
      ``toolset.roles``); undeclared plugins are chat-only;
    * a plugin that declares ``session_scope`` has that argument bound to
      ``~/.berg-agents/projects/<project-id>/<subdir>/<session-key>/``
      and removed from the schema, so a model cannot redirect the store
      and two sessions keep different plans.

    :param agent_role: Who is asking (``chat``, ``planner``, ...).
    :param root_dir: Project root; resolves the project folder.
    :param session_id: Session id, so state is per conversation.
    :return: Ready-to-use tools (possibly empty).
    """
    await ensure_plugin_system_ready()

    tools = collect_plugin_tools(agent_role)
    if not tools:
        return []

    manager = _CACHE["manager"]
    if manager is None:
        return tools

    # Bind per-scope: group the role's tools by the plugin that owns
    # them, because the scope (parameter + directory) is per plugin.
    scopes: dict[str, Any] = {}
    for entry in _plugin_entries():
        scope = getattr(entry.metadata, "session_scope", None)
        if scope is not None:
            scopes[entry.metadata.id] = scope

    if not scopes or root_dir is None:
        # Nothing to bind, or no project root to bind against — the
        # tools stay usable with their own defaults.
        return tools

    from plugin_system.session_scope import bind_session_scope, session_dir_for

    from berg_agents.ui.projects import project_dir, resolve_project

    project = resolve_project(root_dir)
    out: list[Any] = []
    for entry in _plugin_entries():
        if entry.state != PluginState.ENABLED:
            continue
        if not _role_permitted(entry, agent_role):
            continue
        owned = [
            getattr(cap, "tool", None)
            for cap in manager.registry.get_capabilities(
                plugin_id=entry.metadata.id, capability_type="tool"
            )
            if getattr(cap, "tool", None) is not None
        ]
        scope = scopes.get(entry.metadata.id)
        if scope is None:
            out.extend(owned)
            continue
        directory = session_dir_for(
            project_dir(project.id),
            scope.subdir,
            session_id,
            default_key=scope.default_key,
        )
        out.extend(
            bind_session_scope(
                owned, parameter=scope.parameter, directory=directory
            )
        )
    return out


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

    :return: The shared :class:`plugin_system.plugin_manager.PluginManager`.
    :raises RuntimeError: When the manager has not been warmed yet
        (call :func:`ensure_plugin_system_ready` first, which is what
        ``chat_stream`` and the tools endpoint already do).
    """
    manager = _CACHE.get("manager")
    if manager is None:
        raise RuntimeError(
            "Plugin system is not warm yet - call ensure_plugin_system_ready() "
            "before touching the manager."
        )
    return manager


def collect_plugin_tools(agent_role: str = DEFAULT_AGENT_ROLE) -> list[Any]:
    """Collect tools from ENABLED plugins that grant *agent_role*.

    Membership is computed per call (not cached), so toggling a plugin
    takes effect on the next turn without a server restart.

    A plugin grants roles in its manifest (``toolset.roles``); a plugin
    that declares no roles serves the chat agent only, so adding a role
    is always an explicit act. This is what lets one plugin give the
    planner the write tools and an implementer only the tools it needs.

    :param agent_role: Who is asking — ``chat``, ``planner``,
        ``implementer``, or any name a manifest declares.
    :return: Pydantic-ai ``Tool`` objects this role may use.
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
        if not _role_permitted(entry, agent_role):
            continue
        for cap in manager.registry.get_capabilities(
            plugin_id=entry.metadata.id, capability_type="tool"
        ):
            tool = getattr(cap, "tool", None)
            if tool is not None:
                tools.append(tool)
    return tools


def _role_permitted(entry: Any, agent_role: str) -> bool:
    """Whether *entry*'s manifest grants tools to *agent_role*.

    :param entry: Plugin registry entry.
    :param agent_role: Role asking for tools.
    :return: True when the plugin offers its tools to that role.
    """
    roles = tuple(getattr(entry.metadata, "toolset_roles", ()) or ())
    if not roles:
        # No declaration: chat-only, which is what every existing
        # plugin implicitly meant before roles existed.
        return agent_role == DEFAULT_AGENT_ROLE
    return agent_role in roles


async def get_chat_plugin_state(
    *, root_dir: str | None = None, session_id: str | None = None
) -> tuple[list[Any], frozenset[str], frozenset[str]]:
    """Full per-turn plugin state for the chat agent.

    Ensures the cache is warm, then reports what the model may use.

    Tools come from :func:`get_plugin_tools_for` with the ``chat`` role,
    so this path is session-scoped like every other role's: a plugin
    that declares ``session_scope`` gets its store bound to
    *session_id*. Collecting them directly here (the old
    ``collect_plugin_tools``) would hand out tools whose store argument
    still has its manifest default, which means every session would
    share one plan — the exact leak the scope exists to prevent.

    :param root_dir: Project root; needed to resolve the project folder
        a session-scoped store lives under.
    :param session_id: Session id, so state is per conversation.
    :return: ``(tools, disabled_mcp_servers, disabled_skill_ids)`` —
        enabled plugin tools, MCP server keys to exclude from toolsets,
        and chat skill ids (``skill-<name>``) to withhold.
    """
    await ensure_plugin_system_ready()
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
        await get_plugin_tools_for(
            DEFAULT_AGENT_ROLE, root_dir=root_dir, session_id=session_id
        ),
        frozenset(disabled_mcp),
        frozenset(disabled_skills),
    )


async def set_plugin_enabled(plugin_id: str, enabled: bool) -> str | None:
    """Enable or disable one plugin (powers the UI toggles).

    :param plugin_id: Plugin identifier.
    :param enabled: True to enable, False to disable.
    :return: New state string, or None for unknown plugin ids.
    """
    await ensure_plugin_system_ready()
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
        roots = _plugin_search_paths()
        if not roots:
            raise ValueError("no plugin root configured")
        url_suffix = package_dir.relative_to(roots[0]).as_posix()
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
    await ensure_plugin_system_ready()
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
