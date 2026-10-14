"""Event integration for the plugin system."""

from abc import ABC
from typing import Any

from berg_agents.plugin_system.events.event_bus import EventBus, EventHandler
from berg_agents.plugin_system.plugin_context import PluginContext


class EventEmitter:
    """Mixin for plugins to emit events."""

    def __init__(self, plugin_id: str, event_bus: EventBus) -> None:
        self.plugin_id = plugin_id
        self.event_bus = event_bus

    async def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Emit an event from this plugin."""
        await self.event_bus.emit(
            event_type=event_type,
            data=data,
            source=self.plugin_id,
            correlation_id=correlation_id,
        )

    # TODO: Implement EventHandler
    def subscribe(
        self, event_pattern: str, handler: EventHandler, priority: int = 0
    ) -> (
        str
    ):  # TODO: Consider returning a subscription ID or handle for unsubscribing
        """Subscribe to events."""
        return self.event_bus.subscribe(event_pattern, handler, priority)

    def unsubscribe(
        self, event_pattern: str, handler: EventHandler
    ) -> None:  # TODO:  Implement a way to unsubscribe using a subscription ID or handle
        """Unsubscribe from events."""
        self.event_bus.unsubscribe(event_pattern, handler)


class BergPlugin(EventEmitter, ABC):
    """Base plugin with event support."""

    def __init__(self, plugin_id: str, event_bus: EventBus) -> None:
        # EventEmitter initialized by context in on_load
        super().__init__(plugin_id, event_bus)

    async def on_load(self, context: PluginContext) -> None:
        """Initialize event emitter."""
        EventEmitter.__init__(
            self, plugin_id=context.plugin_id, event_bus=context.event_bus
        )
