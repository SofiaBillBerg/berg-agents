"""Plugin registry for managing discovered plugins."""

import asyncio
import logging

from berg_agents.plugin_system.discovery.plugin_entry import PluginEntry
from berg_agents.plugin_system.discovery.plugin_metadata import (
    PluginMetadata,
    PluginSource,
)
from berg_agents.plugin_system.exceptions import PluginError
from berg_agents.plugin_system.lifecycle.lifecycle_states import (
    PluginState,
)
from berg_agents.plugin_system.plugin_contract import PluginCapability

logger = logging.getLogger(__name__)


# Registration Process

# Plugin Registry


class PluginRegistry:
    """Central plugin registry."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginEntry] = {}
        self._capabilities: dict[str, list[PluginCapability]] = {}
        self._lock = asyncio.Lock()

    async def register(self, metadata: PluginMetadata) -> PluginEntry:
        """Register a discovered plugin."""
        async with self._lock:
            if metadata.id in self._plugins:
                raise PluginError(f"Plugin already registered: {metadata.id}")

            entry = PluginEntry(
                metadata=metadata, state=PluginState.DISCOVERED, instance=None
            )

            self._plugins[metadata.id] = entry
            logger.info(f"Registered plugin: {metadata.id} v{metadata.version}")
            return entry

    def update_state(self, plugin_id: str, state: "PluginState") -> None:
        """Update plugin state."""
        if plugin_id in self._plugins:
            self._plugins[plugin_id].state = state

    def get(self, plugin_id: str) -> PluginEntry | None:
        """Get plugin by ID."""
        return self._plugins.get(plugin_id)

    def list_plugins(
            self,
            state: PluginState | None = None,
            source: PluginSource | None = None,
            tag: str | None = None,
    ) -> list[PluginEntry]:
        """List plugins with optional filters."""
        plugins = list(self._plugins.values())

        if state is not None:
            plugins = [p for p in plugins if p.state == state]
        if source is not None:
            plugins = [p for p in plugins if p.metadata.source == source]
        if tag is not None:
            plugins = [p for p in plugins if tag in p.metadata.tags]

        return plugins

    async def register_capability(
            self, plugin_id: str, capability: PluginCapability
    ) -> None:
        """Register a plugin capability."""
        async with self._lock:
            if plugin_id not in self._capabilities:
                self._capabilities[plugin_id] = []
            self._capabilities[plugin_id].append(capability)

    def get_capabilities(
            self, plugin_id: str | None = None, capability_type: str | None = None
    ) -> list[PluginCapability]:
        """Get capabilities with optional filters."""
        if plugin_id:
            caps = self._capabilities.get(plugin_id, [])
        else:
            caps = [c for caps in self._capabilities.values() for c in caps]

        if capability_type:
            caps = [c for c in caps if c.type == capability_type]

        return caps

    async def unregister(self, plugin_id):
        """Unregister a plugin."""
        async with self._lock:
            if plugin_id in self._plugins:
                del self._plugins[plugin_id]
                logger.info(f"Unregistered plugin: {plugin_id}")
            if plugin_id in self._capabilities:
                del self._capabilities[plugin_id]
                logger.info(f"Removed capabilities for plugin: {plugin_id}")
