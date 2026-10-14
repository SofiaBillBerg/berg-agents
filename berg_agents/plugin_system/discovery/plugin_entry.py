"""Plugin entry for the plugin system."""

# Plugin Entry

from dataclasses import dataclass
from datetime import datetime
import logging

from berg_agents.plugin_system.discovery.plugin_metadata import PluginMetadata
from berg_agents.plugin_system.lifecycle.bergplugin import BergPlugin
from berg_agents.plugin_system.lifecycle.lifecycle_states import PluginState

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
