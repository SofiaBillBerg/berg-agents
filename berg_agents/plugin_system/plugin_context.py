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

"""Plugin context - runtime context provided to plugins."""

from pathlib import Path
from typing import Any

from berg_agents import BergAgentsApp, Harness
from berg_agents.plugin_system.events.event_bus import EventBus


class PluginContext:
    """Runtime context provided to plugins."""

    # Plugin metadata
    plugin_id: str
    plugin_version: str
    plugin_dir: Path

    # Berg agents access
    app: BergAgentsApp
    harness: Harness
    config: dict[str, Any]

    # Plugin system
    plugin_manager: Any  # Will be set to PluginManager after import
    event_bus: EventBus
    logger: Any  # logging.Logger

    # Settings
    settings: dict[str, Any]  # Plugin-specific settings

    def __init__(
        self,
        plugin_id: str,
        plugin_version: str,
        plugin_dir: Path,
        app: BergAgentsApp,
        harness: Harness,
        config: dict[str, Any],
        plugin_manager: Any,
        event_bus: EventBus,
        logger: Any,
        settings: dict[str, Any],
    ) -> None:
        self.plugin_id = plugin_id
        self.plugin_version = plugin_version
        self.plugin_dir = plugin_dir
        self.app = app
        self.harness = harness
        self.config = config
        self.plugin_manager = plugin_manager
        self.event_bus = event_bus
        self.logger = logger
        self.settings = settings

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a configuration setting."""
        keys = key.split(".")
        value = self.settings

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    def has_setting(self, key: str) -> bool:
        """Check if setting exists."""
        return self.get_setting(key) is not None
