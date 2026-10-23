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

"""
PluginManager - Central orchestrator for the Berg Agents plugin system.

This class manages the complete plugin lifecycle:
- Discovery and registration
- Dependency resolution
- Loading and initialization
- Lifecycle state management
- Event coordination
- Capability registration
"""

#  Berg Agents Plugin System - Plugin Manager

import asyncio
import importlib
import logging
from pathlib import Path
import sys
from typing import Any

# NOTE: app/harness are typed as Any to avoid a circular import
# (berg_agents/__init__ -> app -> harness -> plugin_system -> app).
# At runtime they are BergAgentsApp and Harness instances.
from berg_agents.plugin_system.config.config_manager import PluginConfigManager
from berg_agents.plugin_system.dependency.dependency_management import (
    DependencyResolver,
)
from berg_agents.plugin_system.discovery.discovery_process import (
    PluginDiscovery,
)
from berg_agents.plugin_system.discovery.plugin_entry import PluginEntry
from berg_agents.plugin_system.discovery.plugin_metadata import PluginMetadata
from berg_agents.plugin_system.discovery.plugin_registry import PluginRegistry
from berg_agents.plugin_system.events.event_bus import EventBus
from berg_agents.plugin_system.exceptions import (
    DependencyError,
    PluginError,
    PluginStateError,
)
from berg_agents.plugin_system.lifecycle.bergplugin import BergPlugin
from berg_agents.plugin_system.lifecycle.lifecycle_states import PluginState
from berg_agents.plugin_system.plugin_context import PluginContext

logger = logging.getLogger(__name__)


def _schema_defaults(schema: Any) -> dict[str, Any]:
    """Pull ``default`` values out of a JSON-schema ``properties`` map.

    :param schema: Plugin settings schema (JSON Schema object or None).
    :return: Flat mapping of property name to declared default.
    """
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    return {
        name: prop["default"]
        for name, prop in properties.items()
        if isinstance(prop, dict) and "default" in prop
    }


class PluginManager:
    """Central plugin system orchestrator.

    Manages the complete plugin lifecycle from discovery through cleanup.
    Coordinates between discovery, registry, dependency resolution, and
    lifecycle management subsystems.
    """

    def __init__(
            self,
            app: Any,
            harness: Any,
            config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize plugin manager.

        Args:
            app: Berg agents application instance (BergAgentsApp).
            harness: Harness instance for agent orchestration (Harness).
            config: Optional configuration overrides
        """
        self.app = app
        self.harness = harness
        self._config = config or {}

        # Core subsystems
        self.registry = PluginRegistry()
        self.event_bus = EventBus()
        self.config_manager = PluginConfigManager()
        self.discovery = PluginDiscovery()
        self.dependency_resolver = DependencyResolver(self.registry)

        # Plugin instances
        self._plugins: dict[str, BergPlugin] = {}
        self._contexts: dict[str, PluginContext] = {}

        # Synchronization
        self._lock = asyncio.Lock()
        self._initialized = False

        logger.info("PluginManager created")

    async def initialize(self) -> None:
        """Initialize the plugin system.

        Sets up event bus, configuration manager, and prepares for plugin discovery.
        Must be called before any other operations.
        """
        if self._initialized:
            logger.warning("PluginManager already initialized")
            return

        logger.info("Initializing plugin system...")

        # Initialize subsystems
        await self.event_bus.initialize()
        await self.config_manager.initialize()

        # Subscribe to system events
        self.event_bus.subscribe("plugin.*", self._handle_plugin_event)

        self._initialized = True
        logger.info("Plugin system initialized")

    async def discover_plugins(
            self, search_paths: list[Path | str]
    ) -> list[PluginMetadata]:
        """Discover plugins in the specified paths.

        Args:
            search_paths: Directories to search for plugins

        Returns:
            List of discovered plugin metadata

        Raises:
            PluginError: If discovery fails
        """
        self._ensure_initialized()

        logger.info(f"Discovering plugins in {len(search_paths)} paths...")

        # Convert to Path objects
        paths = [Path(p) for p in search_paths]

        # Discover plugins
        discovered = await self.discovery.discover_all(paths)

        logger.info(f"Discovered {len(discovered)} plugins")

        # Register discovered plugins
        for metadata in discovered:
            try:
                await self.registry.register(metadata)
                logger.info(f"Registered plugin: {metadata.id}")
            except PluginError as e:
                logger.exception(f"Failed to register {metadata.id}: {e}")

        return discovered

    async def load_plugin(self, plugin_id: str) -> None:
        """Load a single plugin.

        Resolves dependencies, loads the plugin code, and calls on_load hook.

        Args:
            plugin_id: Unique plugin identifier

        Raises:
            PluginError: If loading fails
            DependencyError: If dependencies cannot be resolved
        """
        self._ensure_initialized()

        async with self._lock:
            entry = self.registry.get(plugin_id)  # Not async
            if not entry:
                raise PluginError(f"Plugin not found: {plugin_id}")

            if entry.state != PluginState.DISCOVERED:
                logger.warning(
                    f"Plugin {plugin_id} already in state {entry.state}"
                )
                return

            logger.info(f"Loading plugin: {plugin_id}")

            try:
                # Update state
                self.registry.update_state(plugin_id, PluginState.LOADING)

                # Resolve dependencies
                await self._resolve_dependencies(entry)

                # Import plugin module
                plugin_instance = await self._import_plugin(entry)

                # Create plugin context
                context = await self._create_context(entry)

                # Call on_load hook
                await plugin_instance.on_load(context)

                # Store plugin instance and context
                self._plugins[plugin_id] = plugin_instance
                self._contexts[plugin_id] = context

                # Update state
                self.registry.update_state(plugin_id, PluginState.LOADED)

                logger.info(f"Plugin loaded successfully: {plugin_id}")

                # Emit event
                await self.event_bus.emit(
                    "plugin.loaded",
                    {"plugin_id": plugin_id},
                )

            except Exception as e:
                logger.exception(f"Failed to load plugin {plugin_id}: {e}")
                self.registry.update_state(plugin_id, PluginState.ERROR)
                raise PluginError(f"Failed to load {plugin_id}") from e

    async def enable_plugin(self, plugin_id: str) -> None:
        """Enable a loaded plugin.

        Calls the on_enable hook and registers capabilities with berg_agents.

        Args:
            plugin_id: Unique plugin identifier

        Raises:
            PluginError: If enabling fails
        """
        self._ensure_initialized()

        async with self._lock:
            entry = self.registry.get(plugin_id)  # Not async
            if not entry:
                raise PluginError(f"Plugin not found: {plugin_id}")

            if entry.state != PluginState.LOADED:
                if entry.state == PluginState.ENABLED:
                    logger.warning(f"Plugin already enabled: {plugin_id}")
                    return
                raise PluginStateError(
                    f"Plugin {plugin_id} must be loaded before enabling "
                    f"(current state: {entry.state})"
                )

            logger.info(f"Enabling plugin: {plugin_id}")

            try:
                # Update state
                self.registry.update_state(plugin_id, PluginState.ENABLING)

                plugin = self._plugins[plugin_id]
                context = self._contexts[plugin_id]

                # Call on_enable hook
                await plugin.on_enable(context)

                # Register capabilities
                await self._register_capabilities(plugin_id, plugin)

                # Update state
                self.registry.update_state(plugin_id, PluginState.ENABLED)

                logger.info(f"Plugin enabled successfully: {plugin_id}")

                # Emit event
                await self.event_bus.emit(
                    "plugin.enabled",
                    {"plugin_id": plugin_id},
                )

            except Exception as e:
                logger.exception(f"Failed to enable plugin {plugin_id}: {e}")
                self.registry.update_state(plugin_id, PluginState.ERROR)
                raise PluginError(f"Failed to enable {plugin_id}") from e

    async def disable_plugin(self, plugin_id: str) -> None:
        """Disable an enabled plugin.

        Calls the on_disable hook and unregisters capabilities.

        Args:
            plugin_id: Unique plugin identifier
        """
        self._ensure_initialized()

        async with self._lock:
            entry = self.registry.get(plugin_id)  # Not async
            if not entry or entry.state != PluginState.ENABLED:
                return

            logger.info(f"Disabling plugin: {plugin_id}")

            try:
                self.registry.update_state(plugin_id, PluginState.DISABLING)

                plugin = self._plugins[plugin_id]
                context = self._contexts[plugin_id]

                # Call on_disable hook
                await plugin.on_disable(context)

                # Unregister capabilities
                await self._unregister_capabilities(plugin_id)

                self.registry.update_state(plugin_id, PluginState.LOADED)

                logger.info(f"Plugin disabled: {plugin_id}")

                await self.event_bus.emit(
                    "plugin.disabled",
                    {"plugin_id": plugin_id},
                )

            except Exception as e:
                logger.exception(f"Failed to disable plugin {plugin_id}: {e}")
                self.registry.update_state(plugin_id, PluginState.ERROR)

    async def unload_plugin(self, plugin_id: str) -> None:
        """Unload a plugin completely.

        Args:
            plugin_id: Unique plugin identifier
        """
        self._ensure_initialized()

        # NOTE: disable-then-unload is inlined here instead of calling
        # disable_plugin(), because both methods take self._lock and
        # asyncio.Lock is not re-entrant (nested acquire = deadlock).
        async with self._lock:
            entry = self.registry.get(plugin_id)  # Not async
            if not entry:
                return

            if entry.state == PluginState.ENABLED:
                logger.info(f"Disabling plugin before unload: {plugin_id}")
                try:
                    plugin_enabled = self._plugins.get(plugin_id)
                    context_enabled = self._contexts.get(plugin_id)
                    if (
                            plugin_enabled is not None
                            and context_enabled is not None
                    ):
                        await plugin_enabled.on_disable(context_enabled)
                    await self._unregister_capabilities(plugin_id)
                    self.registry.update_state(plugin_id, PluginState.LOADED)
                    entry = self.registry.get(plugin_id) or entry
                    await self.event_bus.emit(
                        "plugin.disabled",
                        {"plugin_id": plugin_id},
                    )
                except Exception as e:
                    logger.exception(f"Failed to disable plugin {plugin_id}: {e}")
                    self.registry.update_state(plugin_id, PluginState.ERROR)
                    return

            if entry.state != PluginState.LOADED:
                return

            logger.info(f"Unloading plugin: {plugin_id}")

            try:
                plugin = self._plugins[plugin_id]
                context = self._contexts[plugin_id]

                # Call on_unload hook
                await plugin.on_unload(context)

                # Clean up
                del self._plugins[plugin_id]
                del self._contexts[plugin_id]

                self.registry.update_state(plugin_id, PluginState.DISCOVERED)

                logger.info(f"Plugin unloaded: {plugin_id}")

                await self.event_bus.emit(
                    "plugin.unloaded",
                    {"plugin_id": plugin_id},
                )

            except Exception as e:
                logger.exception(f"Failed to unload plugin {plugin_id}: {e}")

    async def load_all(self) -> None:
        """Load all discovered plugins.

        Resolves dependencies and loads plugins in the correct order.
        """
        self._ensure_initialized()

        logger.info("Loading all plugins...")

        # Get all discovered plugins
        entries = self.registry.list_plugins(state=PluginState.DISCOVERED)

        if not entries:
            logger.info("No plugins to load")
            return

        # Get metadata for dependency resolution
        metadata_list = [entry.metadata for entry in entries]

        # Resolve dependencies and get load order.
        # NOTE: resolve() returns (load_order_ids, warnings), not metadata.
        try:
            load_order, warnings = await self.dependency_resolver.resolve(
                metadata_list
            )
            for warning in warnings:
                logger.warning(warning)
        except DependencyError as e:
            logger.exception(f"Failed to resolve dependencies: {e}")
            raise

        logger.info(f"Resolved load order for {len(load_order)} plugins")

        # Load plugins in dependency order
        for plugin_id in load_order:
            try:
                await self.load_plugin(plugin_id or "unknown")
            except Exception as e:
                logger.exception(
                    f"Failed to load {plugin_id or 'unknown'}, continuing: {e}"
                )

        logger.info("Plugin loading complete")

    async def enable_all(self) -> None:
        """Enable all loaded plugins."""
        self._ensure_initialized()

        logger.info("Enabling all plugins...")

        entries = self.registry.list_plugins(state=PluginState.LOADED)

        for entry in entries:
            try:
                await self.enable_plugin(entry.metadata.id or "unknown")
            except Exception as e:
                logger.exception(
                    f"Failed to enable {entry.metadata.id or 'unknown'}: {e}"
                )

        logger.info("Plugin enabling complete")

    async def shutdown(self) -> None:
        """Shutdown the plugin system gracefully."""
        logger.info("Shutting down plugin system...")

        # Disable all enabled plugins
        entries = self.registry.list_plugins(state=PluginState.ENABLED)
        for entry in entries:
            try:
                await self.disable_plugin(entry.metadata.id or "unknown")
            except Exception as e:
                logger.exception(f"Error disabling {entry.metadata.id}: {e}")

        # Unload all loaded plugins
        entries = self.registry.list_plugins(state=PluginState.LOADED)
        for entry in entries:
            try:
                await self.unload_plugin(entry.metadata.id or "unknown")
            except Exception as e:
                logger.exception(f"Error unloading {entry.metadata.id}: {e}")

        # Shutdown event bus
        await self.event_bus.shutdown()

        self._initialized = False
        logger.info("Plugin system shutdown complete")

    def get_plugin(self, plugin_id: str) -> BergPlugin | None:
        """Get a loaded plugin instance.

        Args:
            plugin_id: Unique plugin identifier

        Returns:
            Plugin instance or None if not loaded
        """
        return self._plugins.get(plugin_id)

    async def get_plugin_info(self, plugin_id: str) -> dict[str, Any] | None:
        """Get plugin information.

        Args:
            plugin_id: Unique plugin identifier

        Returns:
            Plugin info dict or None if not found
        """
        entry = self.registry.get(plugin_id or "unknown")
        if not entry:
            return None

        return {
            "id": entry.metadata.id,
            "name": entry.metadata.name,
            "version": entry.metadata.version,
            "state": entry.state,
            "description": entry.metadata.description,
            "author": entry.metadata.author,
            "enabled": entry.state == PluginState.ENABLED}

    async def list_plugins(
            self, state: PluginState | None = None
    ) -> list[dict[str, Any]]:
        """List all plugins.

        Args:
            state: Optional state filter

        Returns:
            List of plugin info dicts
        """
        entries = self.registry.list_plugins(state=state)
        return [
            {
                "id": entry.metadata.id,
                "name": entry.metadata.name,
                "version": entry.metadata.version,
                "state": entry.state,
                "description": entry.metadata.description}
            for entry in entries
        ]

    # Private helper methods

    def _ensure_initialized(self) -> None:
        """Ensure plugin system is initialized."""
        if not self._initialized:
            raise PluginError(
                "PluginManager not initialized. Call initialize() first."
            )

    async def _resolve_dependencies(self, entry: PluginEntry) -> None:
        """Resolve and load plugin dependencies.

        Args:
            entry: Plugin entry to resolve dependencies for

        Raises:
            DependencyError: If dependencies cannot be resolved
        """
        if not entry.metadata.dependencies:
            return

        logger.debug(
            f"Resolving {len(entry.metadata.dependencies)} "
            f"dependencies for {entry.plugin_id}"
        )

        for dep in entry.metadata.dependencies:
            if dep.optional:
                continue

            # Check if dependency is loaded (registry.get is sync).
            dep_entry = self.registry.get(dep.id or "unknown")
            if not dep_entry:
                raise DependencyError(
                    f"Required dependency not found: {dep.id}"
                )

            if dep_entry.state not in (
                    PluginState.LOADED,
                    PluginState.ENABLED,
            ):
                # Try to load dependency first
                await self.load_plugin(dep.id or "unknown")

    async def _import_plugin(self, entry: PluginEntry) -> BergPlugin:
        """Import plugin module and instantiate plugin class.

        Args:
            entry: Plugin entry

        Returns:
            Instantiated plugin

        Raises:
            PluginError: If import fails
        """
        try:
            # Parse entry point: "module.path:ClassName".
            module_path, class_name = entry.metadata.entry_point.split(":")

            # Ensure the plugin directory is importable so local
            # plugins (e.g. berg_plugins/shared-todo) resolve without
            # requiring an installed distribution.
            plugin_dir = entry.metadata.path
            if plugin_dir is not None:
                plugin_dir_str = str(Path(plugin_dir))
                if plugin_dir_str not in sys.path:
                    sys.path.insert(0, plugin_dir_str)

            # Import module
            logger.debug(f"Importing {module_path}")
            module = importlib.import_module(module_path)

            # Get plugin class
            plugin_class = getattr(module, class_name)

            # Instantiate
            plugin_instance = plugin_class()

            if not isinstance(plugin_instance, BergPlugin):
                raise PluginError("Plugin class must inherit from BergPlugin")

            return plugin_instance

        except Exception as e:
            logger.exception(f"Failed to import plugin {entry.plugin_id}: {e}")
            raise PluginError(f"Failed to import {entry.plugin_id}") from e

    async def _load_plugin_settings(self, entry: PluginEntry) -> dict[str, Any]:
        """Resolve a plugin's settings from manifest + config + env.

        Manifest ``settings_schema`` supplies defaults; project
        ``.berg-agents`` is searched for the plugin's documented
        locations; env vars override both. A schema violation is logged
        and degrades to manifest defaults — a plugin with bad config
        still loads, it just runs on defaults.

        :param entry: Plugin entry whose settings are resolved.
        :return: Validated settings mapping (possibly empty).
        """
        from berg_agents.plugin_system.exceptions import ConfigValidationError

        plugin_id = entry.metadata.id or "unknown"
        schema = entry.metadata.settings_schema
        defaults = _schema_defaults(schema)

        try:
            return await self.config_manager.load_config(
                plugin_id, schema=schema, defaults=defaults
            )
        except ConfigValidationError as exc:
            logger.warning(
                "Config for %s invalid (%s); using manifest defaults",
                plugin_id,
                exc,
            )
            return defaults

    async def _create_context(self, entry: PluginEntry) -> PluginContext:
        """Create plugin context.

        Args:
            entry: Plugin entry

        Returns:
            Plugin context
        """
        # Load settings for this plugin: manifest defaults + project
        # .berg-agents + env overrides, validated against the
        # settings_schema the plugin declared. This is the only call
        # that populates the cache — without it context.settings was
        # always empty and every plugin ran on hardcoded defaults.
        settings = await self._load_plugin_settings(entry)

        # PluginContext requires all fields at construction time.
        context = PluginContext(
            plugin_id=entry.metadata.id or "unknown",
            plugin_version=entry.metadata.version,
            plugin_dir=entry.metadata.path or Path(),
            app=self.app,
            harness=self.harness,
            config=self._config,
            plugin_manager=self,
            event_bus=self.event_bus,
            logger=logging.getLogger(f"plugin.{entry.metadata.id}"),
            settings=settings,
        )

        return context

    async def _register_capabilities(
            self, plugin_id: str, plugin: BergPlugin
    ) -> None:
        """Register plugin capabilities with berg_agents.

        Args:
            plugin_id: Plugin identifier
            plugin: Plugin instance
        """
        capabilities = plugin.get_capabilities()

        if not capabilities:
            logger.debug(f"No capabilities for {plugin_id}")
            return

        logger.info(
            f"Registering {len(capabilities)} capabilities for {plugin_id}"
        )

        # NOTE: Register is append-only — clear first so re-enable
        # after disable cannot duplicate capabilities.
        await self.registry.clear_capabilities(plugin_id)

        for cap in capabilities:
            try:
                # Persist every capability in the registry so pilots
                # and UI bridges can enumerate plugin tools/agents.
                await self.registry.register_capability(plugin_id, cap)
                if cap.type == "tool":
                    # Tool registration with the harness happens here
                    # once ToolCatalog gains a plugin-tool slot (later).
                    logger.debug(f"Registering tool: {cap.tool}")
                elif cap.type == "agent":
                    # Register agent
                    logger.debug(f"Registering agent: {cap.agent_class}")
                # Add other capability types as needed

            except Exception as e:
                logger.exception(f"Failed to register capability {cap.type}: {e}")

    async def _unregister_capabilities(self, plugin_id: str) -> None:
        """Unregister plugin capabilities.

        Args:
            plugin_id: Plugin identifier
        """
        logger.debug(f"Unregistering capabilities for {plugin_id}")
        await self.registry.clear_capabilities(plugin_id)

    async def _handle_plugin_event(self, event: Any) -> None:
        """Handle plugin system events.

        Args:
            event: Event object
        """
        logger.debug(f"Plugin event: {event}")
        # Could be used for monitoring, logging, etc.
