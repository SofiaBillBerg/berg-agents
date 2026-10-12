"""Plugin lifecycle management hooks."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from berg_agents.plugin_system.discovery.plugin_entry import PluginEntry
from berg_agents.plugin_system.discovery.plugin_registry import (
    PluginRegistry,
)
from berg_agents.plugin_system.events.event_bus import EventBus
from berg_agents.plugin_system.exceptions import (
    PluginEnableError,
    PluginLoadError,
    PluginNotFoundError,
    PluginStateError,
)
from berg_agents.plugin_system.lifecycle.lifecycle_states import (
    PluginState,
)
from berg_agents.plugin_system.plugin_context import PluginContext
from berg_agents.plugin_system.plugin_contract import (
    PluginCapability,
)

logger = logging.getLogger(__name__)


class PluginLifecycle:
    """Manages plugin lifecycle transitions."""

    def __init__(
            self,
            registry: PluginRegistry,
            event_bus: EventBus,
            config: dict[str, Any],
    ):
        self.registry = registry
        self.event_bus = event_bus
        self.config = config
        self.timeout = config.get("hook_timeout", 30.0)

    async def load(self, plugin_id: str) -> None:
        """Load a plugin."""
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        if entry.state != PluginState.DISCOVERED:
            logger.warning(f"Plugin {plugin_id} already in state {entry.state}")
            return

        # Transition to LOADING
        await self._set_state(entry, PluginState.LOADING)

        try:
            # Import plugin class
            plugin_class = self._import_plugin(entry.metadata.entry_point)

            # Instantiate plugin
            instance = plugin_class()
            entry.instance = instance

            # Create context
            context = await self._create_context(entry)

            # Call on_load hook with timeout
            await asyncio.wait_for(
                instance.on_load(context),
                timeout=self.timeout,
            )

            # Set event bus on plugin
            instance._set_event_bus(self.event_bus, plugin_id)

            # Transition to LOADED
            await self._set_state(entry, PluginState.LOADED)
            entry.loaded_at = datetime.now()

            # Emit event
            await self.event_bus.emit("plugin.loaded", {
                "plugin_id": plugin_id,
                "version": entry.metadata.version})

            logger.info(f"Loaded plugin: {plugin_id}")

        except asyncio.TimeoutError:
            await self._handle_error(entry, PluginLoadError(f"Load timeout: {plugin_id}"))
        except Exception as e:
            await self._handle_error(entry, PluginLoadError(f"Load failed: {e}"))

    async def enable(self, plugin_id: str) -> None:
        """Enable a plugin."""
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        if entry.state == PluginState.ENABLED:
            logger.debug(f"Plugin {plugin_id} already enabled")
            return

        if entry.state != PluginState.LOADED:
            # Auto-load if needed
            if entry.state == PluginState.DISCOVERED:
                await self.load(plugin_id)
            else:
                raise PluginStateError(
                    f"Cannot enable plugin in state {entry.state}"
                )

        # Transition to ENABLING
        await self._set_state(entry, PluginState.ENABLING)

        try:
            context = await self._create_context(entry)

            # Call on_enable hook
            await asyncio.wait_for(
                entry.instance.on_enable(context),
                timeout=self.timeout,
            )

            # Register capabilities
            capabilities = entry.instance.get_capabilities()
            for cap in capabilities:
                await self.registry.register_capability(plugin_id, cap)
                await self._register_capability_with_system(entry, cap)

            # Transition to ENABLED
            await self._set_state(entry, PluginState.ENABLED)
            entry.enabled_at = datetime.now()
            entry.metadata.enabled = True

            # Emit event
            await self.event_bus.emit("plugin.enabled", {
                "plugin_id": plugin_id,
                "capabilities": len(capabilities)})

            logger.info(f"Enabled plugin: {plugin_id}")

        except asyncio.TimeoutError:
            await self._handle_error(entry, PluginEnableError(f"Enable timeout: {plugin_id}"))
        except Exception as e:
            await self._handle_error(entry, PluginEnableError(f"Enable failed: {e}"))

    async def disable(self, plugin_id: str) -> None:
        """Disable a plugin."""
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        if entry.state != PluginState.ENABLED:
            logger.debug(f"Plugin {plugin_id} not enabled")
            return

        # Transition to DISABLING
        await self._set_state(entry, PluginState.DISABLING)

        try:
            context = await self._create_context(entry)

            # Unregister capabilities first
            capabilities = self.registry.get_capabilities(plugin_id)
            for cap in capabilities:
                await self._unregister_capability_from_system(entry, cap)

            # Call on_disable hook
            await asyncio.wait_for(
                entry.instance.on_disable(context),
                timeout=self.timeout,
            )

            # Transition to DISABLED
            await self._set_state(entry, PluginState.DISABLED)
            entry.enabled_at = None
            entry.metadata.enabled = False

            # Emit event
            await self.event_bus.emit("plugin.disabled", {
                "plugin_id": plugin_id})

            logger.info(f"Disabled plugin: {plugin_id}")

        except asyncio.TimeoutError:
            logger.error(f"Disable timeout for {plugin_id}, forcing state change")
            await self._set_state(entry, PluginState.ERROR)
        except Exception as e:
            logger.error(f"Disable failed for {plugin_id}: {e}")
            await self._set_state(entry, PluginState.ERROR)

    async def unload(self, plugin_id: str) -> None:
        """Unload a plugin."""
        entry = self.registry.get(plugin_id)
        if not entry:
            raise PluginNotFoundError(f"Plugin not found: {plugin_id}")

        # Disable first if enabled
        if entry.state == PluginState.ENABLED:
            await self.disable(plugin_id)

        if entry.state not in (PluginState.LOADED, PluginState.DISABLED, PluginState.ERROR):
            logger.debug(f"Plugin {plugin_id} cannot be unloaded from state {entry.state}")
            return

        # Transition to UNLOADING
        await self._set_state(entry, PluginState.UNLOADING)

        try:
            if entry.instance:
                context = await self._create_context(entry)

                # Call on_unload hook
                await asyncio.wait_for(
                    entry.instance.on_unload(context),
                    timeout=self.timeout,
                )

            # Remove from registry
            await self.registry.unregister(plugin_id)

            # Emit event
            await self.event_bus.emit("plugin.unloaded", {
                "plugin_id": plugin_id})

            logger.info(f"Unloaded plugin: {plugin_id}")

        except asyncio.TimeoutError:
            logger.error(f"Unload timeout for {plugin_id}, forcing removal")
            await self.registry.unregister(plugin_id)
        except Exception as e:
            logger.error(f"Unload failed for {plugin_id}: {e}")
            await self.registry.unregister(plugin_id)

    async def _handle_error(self, entry: PluginEntry, error: Exception) -> None:
        """Handle plugin error."""
        logger.error(f"Plugin error: {entry.metadata.id}: {error}")

        # Store error
        entry.error = error

        # Transition to ERROR state
        await self._set_state(entry, PluginState.ERROR)

        # Call on_error hook if instance exists
        if entry.instance:
            try:
                context = await self._create_context(entry)
                await entry.instance.on_error(context, error)
            except Exception as e:
                logger.error(f"on_error hook failed: {e}")

        # Emit event
        await self.event_bus.emit("plugin.error", {
            "plugin_id": entry.metadata.id,
            "error": str(error)})

    async def _set_state(self, entry: PluginEntry, state: PluginState) -> None:
        """Set plugin state."""
        old_state = entry.state
        entry.state = state
        logger.debug(f"Plugin {entry.metadata.id}: {old_state} -> {state}")

    def _import_plugin(self, entry_point: str) -> type:
        """Import plugin class from entry point."""
        module_path, class_name = entry_point.rsplit(":", 1)
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    async def _create_context(self, entry: PluginEntry) -> PluginContext:
        """Create plugin context."""
        from berg_agents import BergAgentsApp, Harness

        return PluginContext(
            plugin_id=entry.metadata.id,
            plugin_version=entry.metadata.version,
            plugin_dir=entry.metadata.path,
            app=BergAgentsApp(),  # Will be set by plugin manager
            harness=Harness(),
            config=self.config,
            plugin_manager=None,  # Will be set by plugin manager
            event_bus=self.event_bus,
            logger=logger,
            settings=entry.metadata.settings_schema or {},
        )

    async def _register_capability_with_system(
            self, entry: PluginEntry, capability: PluginCapability
    ) -> None:
        """Register capability with berg_agents system."""
        # This would integrate with berg_agents capability system
        pass

    async def _unregister_capability_from_system(
            self, entry: PluginEntry, capability: PluginCapability
    ) -> None:
        """Unregister capability from berg_agents system."""
        pass
