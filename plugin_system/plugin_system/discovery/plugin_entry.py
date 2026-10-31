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

"""Plugin entry for the plugin system."""

# Plugin Entry

from dataclasses import dataclass
from datetime import datetime
import logging

from plugin_system.discovery.plugin_metadata import PluginMetadata
from plugin_system.lifecycle.bergplugin import BergPlugin
from plugin_system.lifecycle.lifecycle_states import PluginState

logger = logging.getLogger(__name__)


@dataclass
class PluginEntry:
    """Registry entry for a plugin."""

    metadata: PluginMetadata
    state: PluginState
    instance: BergPlugin | None

    loaded_at: datetime | None = None
    enabled_at: datetime | None = None
    error: Exception | None = None
    plugin_id: str | None = None

    def is_enabled(self) -> bool:
        """Check if plugin is enabled."""
        return self.state == PluginState.ENABLED

    def is_loaded(self) -> bool:
        """Check if plugin is loaded."""
        return self.state in {PluginState.LOADED, PluginState.ENABLED}
