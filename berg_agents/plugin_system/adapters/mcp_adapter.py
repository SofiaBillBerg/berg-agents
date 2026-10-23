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

"""Front one MCP server (.berg-agents /mcp.json entry) as a plugin.

Migration-guide Phase 1: MCP servers keep working exactly as before —
no configuration file moves and no rewrites. Each server becomes one
``MCPPluginAdapter`` exposing an ``MCPCapability`` descriptor, so
servers gain plugin lifecycle, events, and UI visibility while the
chat agent keeps attaching their toolsets through the existing
:mod:`berg_agents.capabilities.mcp_toolsets` path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from berg_agents.plugin_system.discovery.plugin_metadata import PluginMetadata
from berg_agents.plugin_system.lifecycle.bergplugin import BergPlugin
from berg_agents.plugin_system.plugin_context import PluginContext
from berg_agents.plugin_system.plugin_contract import MCPCapability

logger = logging.getLogger(__name__)

#: Entry point shared by every MCP plugin (the server key travels via
#: per-plugin settings, see register_mcp_plugins).
ENTRY_POINT = "berg_agents.plugin_system.adapters.mcp_adapter:MCPPluginAdapter"


def mcp_plugin_id(server_name: str) -> str:
    """Plugin id for an MCP server (``berg-plugin-mcp-<name>``).

    :param server_name: MCP server key from .berg-agents /mcp.json.
    :return: Namespaced plugin identifier.
    """
    return f"berg-plugin-mcp-{server_name}"


class MCPPluginAdapter(BergPlugin):
    """Wraps one MCP server as a plugin.

    The server key arrives via plugin settings (``server_name``),
    seeded by :func:`register_mcp_plugins` — the shared entry point
    cannot carry per-server arguments. Live tool enumeration stays
    with the toolset layer (it needs a running session); this adapter
    owns descriptor, lifecycle, and events.
    """

    def __init__(self) -> None:
        """Initialize the adapter (descriptor loads in on_load)."""
        super().__init__()
        self.server_name = ""
        self.server_type = ""
        self.enabled = True
        self.sensitive = False

    async def on_load(self, context: PluginContext) -> None:
        """Read the server entry from .berg-agents /mcp.json.

        :param context: Plugin context carrying ``server_name`` settings.
        """
        self._set_event_bus(context.event_bus, context.plugin_id)
        server_name = (context.settings or {}).get("server_name", "")
        if not server_name:
            logger.warning(
                "MCP plugin %s has no server_name setting", context.plugin_id
            )
            return
        # NOTE: Reuses the chat MCP config reader so transport rules
        # stay identical between the adapter and the chat agent.
        from berg_agents.capabilities.mcp_toolsets import _load_config
        from berg_agents.core.mcp import is_sensitive_server

        entry = _load_config().get(server_name)
        if not isinstance(entry, dict):
            logger.warning(
                "MCP server %r not in .berg-agents, skipping", server_name
            )
            return
        self.server_name = server_name
        self.server_type = str(entry.get("type", "")).strip().lower()
        self.enabled = entry.get("enabled", True) is not False
        self.sensitive = is_sensitive_server(server_name)
        logger.info(
            "MCP plugin loaded: %s (%s, sensitive=%s)",
            server_name,
            self.server_type,
            self.sensitive,
        )

    async def on_disable(self, context: PluginContext) -> None:
        """Disable the plugin (toolset sessions close via their owner).

        :param context: Plugin context.
        """
        logger.info("MCP plugin disabled: %s", self.server_name)

    async def on_unload(self, context: PluginContext) -> None:
        """Unload the plugin.

        :param context: Plugin context.
        """
        logger.info("MCP plugin unloaded: %s", self.server_name)

    def get_capabilities(self) -> list[MCPCapability]:
        """Return the MCP server descriptor (empty when unloaded).

        :return: One ``MCPCapability`` once on_load read the configuration file in .berg-agents directory.
        """
        if not self.server_name:
            return []
        return [
            MCPCapability(
                id=self.server_name,
                server_type=self.server_type,
                enabled=self.enabled,
                sensitive=self.sensitive,
                tool_prefix=f"mcp_{self.server_name}_",
            )
        ]


def build_mcp_metadata(
    server_name: str, server_type: str = ""
) -> PluginMetadata:
    """Build registry metadata for one MCP server.

    :param server_name: MCP server key from .berg-agents /mcp.json.
    :param server_type: Transport kind (``remote``/``local``/``""``).
    :return: Plugin metadata pointing at the shared adapter entry point.
    """
    return PluginMetadata(
        id=mcp_plugin_id(server_name),
        version="0.0.1",
        name=f"MCP: {server_name}",
        description=(
            f"MCP server '{server_name}' ({server_type or 'unknown type'}). "
            "Tools attach to the chat agent via its toolset."
        ),
        source="local",
        path=Path(__file__).resolve().parents[3] / ".berg-agents",
        entry_point=ENTRY_POINT,
        tags=["mcp"],
    )


def describe_mcp_server(server_name: str) -> dict[str, Any] | None:
    """Describe an MCP server from configuration without a running plugin.

    Used for descriptors of disabled plugins (whose capabilities are
    unregistered): same reader as the adapter and the chat toolsets.

    :param server_name: MCP server key from .berg-agents /mcp.json.
    :return: Capability-style descriptor, or None when unconfigured.
    """
    from berg_agents.capabilities.mcp_toolsets import _load_config
    from berg_agents.core.mcp import is_sensitive_server

    entry = _load_config().get(server_name)
    if not isinstance(entry, dict):
        return None
    return {
        "type": "mcp",
        "id": server_name,
        "name": server_name,
        "server_type": str(entry.get("type", "")).strip().lower(),
        "enabled": entry.get("enabled", True) is not False,
        "sensitive": is_sensitive_server(server_name)}


async def register_mcp_plugins(manager: Any) -> list[str]:
    """Register every configured MCP server as an adapter plugin.

    Uses the manager's existing machinery only: metadata goes into the
    registry, the server key goes into per-plugin settings (unpersisted),
    and the standard load_all/enable_all lifecycle picks them up.

    :param manager: Initialized ``PluginManager``.
    :return: Registered plugin ids.
    """
    # NOTE: Same config reader as the chat toolsets — adapter and chat
    # can never disagree about which servers exist.
    from berg_agents.capabilities.mcp_toolsets import _load_config
    from berg_agents.plugin_system.exceptions import PluginError

    registered: list[str] = []
    for server_name, entry in _load_config().items():
        if not isinstance(entry, dict):
            continue
        metadata = build_mcp_metadata(
            server_name, str(entry.get("type", "")).strip().lower()
        )
        if manager.registry.get(metadata.id) is not None:
            continue
        try:
            await manager.registry.register(metadata)
        except PluginError as exc:
            logger.warning("MCP plugin registration skipped: %s", exc)
            continue
        # NOTE: persisted. The server key must survive a restart: an
        # in-memory cache dies with the process, so every adapter
        # reloaded with empty settings (observed as "has no server_name
        # setting" spam at startup and inert MCP plugins).
        await manager.config_manager.update(
            metadata.id, {"server_name": server_name}, persist=True
        )
        registered.append(metadata.id)
        logger.info("MCP plugin registered: %s", metadata.id)
    return registered


async def sync_mcp_config_states(manager: Any) -> None:
    """Align plugin states with ``enabled: false`` configuration entries.

    Runs once after enable_all at warmup: config-off servers move to
    disabled state so the config kill-switch works through the same
    mechanism as the UI toggles (and the chat exclusion sets pick
    them up). Never enables anything — user toggles are one-way here.

    :param manager: Initialized ``PluginManager`` with MCP plugins.
    """
    from berg_agents.capabilities.mcp_toolsets import _load_config

    config = _load_config()
    for mcp_entry in manager.registry.list_plugins():
        plugin_id = mcp_entry.metadata.id
        if not plugin_id.startswith("berg-plugin-mcp-"):
            continue
        server_name = plugin_id.removeprefix("berg-plugin-mcp-")
        cfg = config.get(server_name)
        config_off = (
            not isinstance(cfg, dict) or cfg.get("enabled", True) is False
        )
        if config_off:
            try:
                await manager.disable_plugin(plugin_id)
                logger.info(
                    "MCP plugin disabled by configuration: %s", server_name
                )
            except Exception as exc:
                logger.warning("MCP configuration sync failed: %s", exc)
