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

"""Event integration for the plugin system."""

from abc import ABC
from typing import Any

from plugin_system.events.event_bus import EventBus, EventHandler
from plugin_system.plugin_context import PluginContext


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
