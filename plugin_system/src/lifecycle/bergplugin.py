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

"""Base class for all berg_agents plugins."""

from __future__ import annotations

import logging

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from plugin_system.plugin_context import PluginContext
from plugin_system.plugin_contract import PluginCapability


if TYPE_CHECKING:
    from plugin_system.events.event_bus import EventBus

logger = logging.getLogger(__name__)


class BergPlugin(ABC):
    """Base class for all berg_agents plugins."""

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._event_bus: EventBus | None = None
        self._plugin_id: str | None = None

    # === Lifecycle Hooks ===

    @abstractmethod
    async def on_load(self, context: PluginContext) -> None:
        """Called when plugin is loaded."""

    async def on_enable(self, context: PluginContext) -> None:
        """Called when plugin is enabled."""

    async def on_disable(self, context: PluginContext) -> None:
        """Called when plugin is disabled."""

    async def on_unload(self, context: PluginContext) -> None:
        """Called when plugin is unloaded."""

    async def on_error(self, context: PluginContext, error: Exception) -> None:
        """Called when plugin encounters an error."""

    async def on_config_change(
        self, context: PluginContext, new_config: dict[str, Any]
    ) -> None:
        """Called when plugin configuration changes."""

    async def health_check(self, context: PluginContext) -> Any:  # ruff: ignore[no-self-use]
        """Check plugin health.

        :param context: The plugin context.
        :return: A HealthStatus object indicating the health of the plugin.
        """
        from plugin_system.lifecycle.health_status import HealthStatus

        return HealthStatus(status="healthy")

    # === Capabilities ===

    def get_capabilities(self) -> list[PluginCapability]:  # ruff: ignore[no-self-use]
        """Return plugin capabilities."""
        return []

    def get_settings_schema(self) -> dict[str, Any] | None:
        """Return JSON schema for plugin settings."""
        return None

    # === Event Helpers ===

    async def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Emit an event from this plugin."""
        if self._event_bus and self._plugin_id:
            await self._event_bus.emit(
                event_type=event_type,
                data=data,
                source=self._plugin_id,
                correlation_id=correlation_id,
            )

    def subscribe(
        self, event_pattern: str, handler: Any, priority: int = 0
    ) -> str:
        """Subscribe to events."""
        if self._event_bus:
            return self._event_bus.subscribe(event_pattern, handler, priority)
        return ""

    def unsubscribe(self, event_pattern: str, handler: Any) -> None:
        """Unsubscribe from events."""
        if self._event_bus:
            self._event_bus.unsubscribe(event_pattern, handler)

    # === Internal methods ===

    def _set_event_bus(self, event_bus: EventBus, plugin_id: str) -> None:
        """Set the event bus (called by PluginContext)."""
        self._event_bus = event_bus
        self._plugin_id = plugin_id
