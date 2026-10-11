"""Plugin entry for the plugin system."""
#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

# Plugin Entry


from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from feat_dev.plugin_dev.plugin_system.discovery.plugin_metadata import PluginMetadata
    from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_states import PluginState
from datetime import datetime
import logging

from feat_dev.plugin_dev.plugin_system.discovery.plugin_metadata import (
    PluginMetadata,
)
from feat_dev.plugin_dev.plugin_system.lifecycle.bergplugin import BergPlugin
from feat_dev.plugin_dev.plugin_system.lifecycle.lifecycle_states import (
    PluginState,
)

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
